import logging
import queue
import threading

from prometheus_client import Gauge

from myblinkstick.heap import HeapBy

# Outside the class so that during unit testing, the gauge isn't redefined
hasBlinkstickGauge = Gauge(
        'hasBlinkstick',
        '1 if a blinkstick is found, 0 otherwise' )
hasBlinkstickGauge.set( 0 )

blinkstickAlerts = Gauge(
        'blinkstick_alerts',
        'active blinksticks alerts (not masked)',
        ['name'] )

class BlinkstickThread( threading.Thread ):
    def __init__( self, config, *args, **kwargs ):
        super().__init__( *args, **kwargs )
        self._message_queue = queue.Queue()

        for alert in config["alerts"]:
            blinkstickAlerts.labels( alert["name"] ).set( 0 )

        # TODO: validate that all the channels are between 0 and 7

        # A convenience function for getting the alert for a given alert name
        self._alerts = {}
        i = 0
        logging.debug( config )
        for alert in config["alerts"]:
            self._alerts[alert["name"]] = alert

            if "priority" not in self._alerts[alert["name"]]:
                self._alerts[alert["name"]]["priority"] = i
                i += 1
        logging.debug( self._alerts )

        hasBlinkstickGauge.set( 0 )


    def enqueue( self, message ):
        self._message_queue.put( message )


    # TODO: make life easy: implement an __exit__ (or whatever it's called)
    def terminate( self ):
        self.enqueue( { "terminate": True } )

    # TODO: move to DTO
    def get_visible_alerts( self ):
        # TODO: wait for a reply. We can't just inspect the value: we need to
        # wait for our messages to be parsed
        reply_queue = queue.Queue()
        message = { "replyQueue":       reply_queue,
                    "getVisibleAlerts": True }
        self.enqueue( message )
        return reply_queue.get()

    # TODO: move to DTO
    def get_current_alerts( self ):
        reply_queue = queue.Queue()
        message = { "replyQueue":        reply_queue,
                    "getCurrentAlerts":  True }
        self.enqueue( message )
        return reply_queue.get()


    def run( self ):
        message_queue = self._message_queue

        current_alerts = []
        for i in range( 0, 8 ):
            # A heap of tuples: (alert, client)
            current_alerts.append( {} )

        last_printed = [None, None, None, None, None, None, None, None]
        def potentially_print_state( current ):
            nonlocal last_printed
            if current != last_printed:
                logging.info( current )
                last_printed = current

        def noop_update_alert( alert ):
            nonlocal last_printed
            current = last_printed.copy()
            current[self._alerts[alert["name"]]["channel"]] = alert["name"]
            potentially_print_state( current )
        update_alert = noop_update_alert
        def noop_clear_channel( channel ):
            nonlocal last_printed
            current = last_printed.copy()
            current[channel] = None
            potentially_print_state( current )
        clear_channel = noop_clear_channel

        stick = None
        try:
            import usb                        # pylint: disable=import-outside-toplevel
            from blinkstick import blinkstick # pylint: disable=import-outside-toplevel

            sticks = blinkstick.find_all()
            if len( sticks ) == 0:
                logging.error( "no blink sticks found!" )
            else:
                hasBlinkstickGauge.set( 1 )
                logging.debug( len( sticks ) )
                stick = sticks[0]
                logging.debug( stick )

                def update_blinkstick_alert( alert ):
                    # TODO: put this on a blinkstick specific logger
                    # TODO: normalize with the noonpUpdateAlert / noopClearChannel
                    logging.debug( "channel: %s; color: %s",
                                   str( self._alerts[alert["name"]]["channel"]),
                                   str( self._alerts[alert["name"]]["color"] ) )
                    stick.set_color( index=self._alerts[alert["name"]]["channel"],
                                     name=self._alerts[alert["name"]]["color"] )
                def clear_blinkstick_channel( channel ):
                    logging.debug( "channel: %s; color: black",
                                   str( channel ) )
                    stick.set_color( index=channel,
                                     name="black" )

                update_alert = update_blinkstick_alert
                clear_channel = clear_blinkstick_channel

            # Turn the led off, if it was left on by a previous invocation
            for i in range( 0, 8 ):
                clear_channel( i )

        except (usb.core.USBError, usb.core.NoBackendError):
            logging.error( "no blinksticks found!" )

        except ModuleNotFoundError:
            logging.error( "no blinksticks found!" )

        # Continue to process events, even if no blink stick is found. It's useful for debugging.
        # TODO: periodically look for a blink stick being connected or disconnected?
        while True:
            message = message_queue.get( block=True )
            logging.debug( str( message ) )
            try:
                if "terminate" in message and message["terminate"]:
                    return

                elif "enable" in message or "disable" in message:
                    alert_name = message["enable"] if "enable" in message else message["disable"]
                    logging.debug( alert_name )

                    if alert_name not in self._alerts:
                        logging.debug( "unrecognized alert: %s; known alerts: %s",
                                       str( alert_name ),
                                       str( self._alerts ) )
                        # Someone is trying to set an alert that doesn't exist. Continue on like
                        # nothing has happened.
                        continue

                    channel = self._alerts[alert_name]["channel"]
                    if alert_name not in current_alerts[channel]:
                        current_alerts[channel][alert_name] = set()

                    if "enable" in message:
                        current_alerts[channel][alert_name].add( message["source"] )
                    else:
                        if alert_name in current_alerts[channel]:
                            if message["source"] in current_alerts[channel][alert_name]:
                                current_alerts[channel][alert_name].remove( message["source"] )

                            if len( current_alerts[channel][alert_name] ) == 0:
                                del current_alerts[channel][alert_name]
                    blinkstickAlerts.labels(alert_name).set(
                        alert_name in current_alerts[channel] and len( current_alerts[channel][alert_name] ) > 0 )

                elif "register" in message:
                    pass

                elif "unregister" in message:
                    for i in range( 0, 8 ):
                        for alert in list( current_alerts[i].keys() ):
                            if alert in current_alerts[i] and \
                               message["unregister"] in current_alerts[i][alert]:
                                current_alerts[i][alert].remove( message["unregister"] )
                            if len( current_alerts[i][alert] ) == 0:
                                del current_alerts[i][alert]

                elif "getCurrentAlerts" in message:
                    message["replyQueue"].put( current_alerts.copy() )


                result = []
                for i in range( 0, 8 ):
                    heap = HeapBy( lambda x: x["priority"] )
                    for alert in current_alerts[i]:
                        heap.push( self._alerts[alert] )

                    if heap.size() > 0:
                        result.append( heap.peek()["name"] )
                        update_alert( heap.peek() )
                    else:
                        result.append( None )
                        clear_channel( i )

                if "getVisibleAlerts" in message:
                    message["replyQueue"].put( result )


            except Exception as e:
                logging.exception( e )


class BlinkstickDTO( object ):
    def __init__( self, blinkstick_thread: BlinkstickThread, client_identifier: str ):
        self._blinkstick_thread = blinkstick_thread
        self._client_identifier = client_identifier


    def enable( self, alert ):
        self._blinkstick_thread.enqueue( { "enable": alert,
                                           "source": self._client_identifier } )


    def disable( self, alert ):
        self._blinkstick_thread.enqueue( { "disable": alert,
                                           "source":  self._client_identifier } )


    def register( self ):
        self._blinkstick_thread.enqueue( { "register": self._client_identifier } )


    def unregister( self ):
        self._blinkstick_thread.enqueue( { "unregister": self._client_identifier } )
