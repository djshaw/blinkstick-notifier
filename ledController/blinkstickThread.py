import logging
import queue
import threading
import usb

from heap import HeapBy

from prometheus_client import Gauge

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
        self._messageQueue = queue.Queue()

        for alert in config:
            blinkstickAlerts.labels( alert["name"] ).set( 0 )

        # TODO: validate that all the channels are between 0 and 7

        # A convenience function for getting the alert for a given alert name
        self._alerts = {}
        i = 0
        logging.debug( config )
        for alert in config:
            self._alerts[alert["name"]] = alert

            if "priority" not in self._alerts[alert["name"]]:
                self._alerts[alert["name"]]["priority"] = i
                i += 1
        logging.debug( self._alerts )

        hasBlinkstickGauge.set( 0 )


    def enqueue( self, message ):
        self._messageQueue.put( message )


    # TODO: make life easy: implement an __exit__ (or whatever it's called)
    def terminate( self ):
        self.enqueue( { "terminate": True } )


    def getVisibleAlerts( self ):
        # TODO: wait for a reply. We can't just inspect the value: we need to
        # wait for our messages to be parsed
        replyQueue = queue.Queue()
        message = { "replyQueue":       replyQueue,
                    "getVisibleAlerts": True }
        self.enqueue( message )
        return replyQueue.get()


    def getCurrentAlerts( self ):
        replyQueue = queue.Queue()
        message = { "replyQueue":        replyQueue,
                    "getCurrentAlerts":  True }
        self.enqueue( message )
        return replyQueue.get()


    def run( self ):
        global alertPrioritiesMap

        messageQueue = self._messageQueue

        currentAlerts = []
        for i in range( 0, 8 ):
            # A heap of tuples: (alert, client)
            currentAlerts.append( {} )

        lastPrinted = [None, None, None, None, None, None, None, None]
        def potentiallyPrintState( current ):
            nonlocal lastPrinted
            if current != lastPrinted:
                logging.info( current )
                lastPrinted = current

        def noopUpdateAlert( alert ):
            nonlocal lastPrinted
            current = lastPrinted.copy()
            current[self._alerts[alert["name"]]["channel"]] = alert["name"]
            potentiallyPrintState( current )
        updateAlert = noopUpdateAlert
        def noopClearChannel( channel ):
            nonlocal lastPrinted
            current = lastPrinted.copy()
            current[channel] = None
            potentiallyPrintState( current )
        clearChannel = noopClearChannel

        stick = None
        try:
            from blinkstick import blinkstick

            sticks = blinkstick.find_all()
            if len( sticks ) == 0:
                logging.error( "no blink sticks found!" )
            else:
                hasBlinkstickGauge.set( 1 )
                logging.debug( len( sticks ) )
                stick = sticks[0]
                logging.debug( stick )

                def updateBlinkstickAlert( alert ):
                    # TODO: put this on a blinkstick specific logger
                    # TODO: normalize with the noonpUpdateAlert / noopClearChannel
                    logging.debug( "channel: " + str( self._alerts[alert["name"]]["channel"]) + "; color: " + str( self._alerts[alert["name"]]["color"] ) )
                    stick.set_color( index=self._alerts[alert["name"]]["channel"],
                                     name=self._alerts[alert["name"]]["color"] )
                def clearBlinkstickChannel( channel ):
                    logging.debug( "channel: " + str( channel ) + "; color: black" )
                    stick.set_color( index=channel,
                                    name="black" )

                updateAlert = updateBlinkstickAlert
                clearChannel = clearBlinkstickChannel

            # Turn the led off, if it was left on by a previous invocation
            for i in range( 0, 8 ):
                clearChannel( i )

        except usb.core.USBError as e:
            logging.error( "no blinksticks found!" )

        except ModuleNotFoundError as e:
            logging.error( "no blinksticks found!" )

        # Continue to process events, even if no blink stick is found. It's useful for debugging.
        # TODO: periodically look for a blink stick being connected or disconnected?
        while True:
            message = messageQueue.get( block=True )
            logging.debug( str( message ) )
            try:
                if "terminate" in message and message["terminate"]:
                    return

                elif "enable" in message or "disable" in message:
                    alertName = message["enable"] if "enable" in message else message["disable"]
                    logging.debug( alertName )

                    if alertName not in self._alerts:
                        logging.debug( "unrecognized alert: " + str( alertName ) + "; known alerts: " + str( self._alerts ) )
                        # Someone is trying to set an alert that doesn't exist. Continue on like
                        # nothing has happened.
                        continue

                    channel = self._alerts[alertName]["channel"]
                    if alertName not in currentAlerts[channel]:
                        currentAlerts[channel][alertName] = set()

                    if "enable" in message:
                        currentAlerts[channel][alertName].add( message["source"] )
                    else:
                        if alertName in currentAlerts[channel]:
                            if message["source"] in currentAlerts[channel][alertName]:
                                currentAlerts[channel][alertName].remove( message["source"] )

                            if len( currentAlerts[channel][alertName] ) == 0:
                                del currentAlerts[channel][alertName]
                    blinkstickAlerts.labels(alertName).set(
                        alertName in currentAlerts[channel] and len( currentAlerts[channel][alertName] ) > 0 )

                elif "register" in message:
                    pass

                elif "unregister" in message:
                    for i in range( 0, 8 ):
                        for alert in list( currentAlerts[i].keys() ):
                            if alert in currentAlerts[i]:
                                currentAlerts[i][alert].remove( message["unregister"] )
                            if len( currentAlerts[i][alert] ) == 0:
                                del currentAlerts[i][alert]

                elif "getCurrentAlerts" in message:
                    message["replyQueue"].put( currentAlerts.copy() )


                result = []
                for i in range( 0, 8 ):
                    heap = HeapBy( lambda x: x["priority"] )
                    for alert in currentAlerts[i]:
                        heap.push( self._alerts[alert] )

                    if heap.size() > 0:
                        result.append( heap.peek()["name"] )
                        updateAlert( heap.peek() )
                    else:
                        result.append( None )
                        clearChannel( i )

                if "getVisibleAlerts" in message:
                    message["replyQueue"].put( result )


            except Exception as e:
                logging.exception( e )


class BlinkstickDTO( object ):
    def __init__( self, blinkstickThread, clientIdentifier=None, *args, **kwargs ):
        super().__init__( *args, **kwargs )
        self._blinkstickThread = blinkstickThread
        self._clientIdentifier = clientIdentifier


    def enable( self, alert ):
        self._blinkstickThread.enqueue( { "enable": alert,
                                          "source": self._clientIdentifier } )


    def disable( self, alert ):
        self._blinkstickThread.enqueue( { "disable": alert,
                                          "source":  self._clientIdentifier } )


    def register( self ):
        self._blinkstickThread.enqueue( { "register": self._clientIdentifier } )


    def unregister( self ):
        self._blinkstickThread.enqueue( { "unregister": self._clientIdentifier } )


