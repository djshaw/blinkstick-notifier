import json
import logging
import threading

from threading import Lock, Semaphore

import websocket

from prometheus_client import Counter

websocketsOpenCounter = Counter(
        'websocketsOpen',
        'The number of times we attempted to establish a websocket connection to the controller' )
websocketOpenedCounter = Counter(
        'websocketsOpened',
        'The number of times we successfully established a websocket connection to the controller' )
websocketOpenTimeout = Counter(
        'websocketsOpenTimedOut',
        'The number of times we timed out attempting to establish a websocket connection to the controller' )
websocketSendIOExceptions = Counter(
        'websocketSendIOExceptions',
        'The number of IOExceptions that have occurred while sending a message' )
websocketMessagesSent = Counter(
        'websocketMessagesSent',
        'The number of messages sent over the websocket' )
websocketOnOpen = Counter(
        'websocketOnOpen',
        'The number of times an on_open was called for the websocket' )
websocketMessageReceived = Counter(
        'websocketMessageReceived',
        'The number of times an on_message was called for the websocket, '
            'ostensibly the messages received on the websocket' )
websocketOnError = Counter(
        'websocketOnError',
        'The number of times an on_error was called for the websocket' )
websocketOnClose = Counter(
        'websocketOnClose',
        'The number of times an on_close was called for the websocket' )


class WebsocketClient( threading.Thread ):
    def __init__( self, url, *args, name=None, httpPathPrefix=None, **kwargs ):
        threading.Thread.__init__( self, daemon=True )
        self._websocket_thread = None

        self._url = url
        self._state_mutex = Lock()
        self._state = set()
        self._has_event = Semaphore( 0 )
        self._name = name
        self._http_path_prefix = httpPathPrefix

        self._websocket = None

    def __enter__( self ):
        self.start()
        return self

    def __exit__( self, *args ):
        self.stop()

    def enable( self, alert ):
        with self._state_mutex:
            self._state.add( alert )
        self._has_event.release()

    def disable( self, alert ):
        with self._state_mutex:
            if alert in self._state:
                self._state.remove( alert )
        self._has_event.release()

    def stop( self ):
        if self._websocket is not None:
            self._websocket.close()

    def run( self ):
        try:
            logger = logging.getLogger( __class__.__name__ )

            def open_websocket():
                open_sem = threading.Semaphore( 0 )
                def on_open( ws ):
                    try:
                        if self._name is not None:
                            m = { "name": self._name }
                            if self._http_path_prefix is not None:
                                m["link"] = self._http_path_prefix
                            ws.send( json.dumps( m ).encode( "ascii" ) )
                        with self._state_mutex:
                            for alert in self._state:
                                # TODO: use the same sendMessage as below. Logging in the one below
                                # isn't necessary duplicated here
                                ws.send( json.dumps( { "enable": alert } ).encode( "ascii" ) )

                        open_sem.release()

                    except Exception as e:
                        logger.exception( e )

                def on_message( ws, message ):
                    # This websocket will only receive responses. We can ignore them for the most part
                    websocketMessageReceived.inc( 1 )

                def on_error( ws, error ):
                    websocketOnError.inc( 1 )

                def on_close( ws, close_code, close_message ):
                    websocketOnClose.inc( 1 )


                while True:
                    if self._websocket_thread is not None:
                        # TODO: close the websocket if it hasn't been already closed
                        self._websocket_thread.join()

                    websocketsOpenCounter.inc( 1 )
                    ws = websocket.WebSocketApp( self._url,
                                                 on_open=on_open,
                                                 on_message=on_message,
                                                 on_error=on_error,
                                                 on_close=on_close )
                    websocket_app_thread = threading.Thread(
                        target=ws.run_forever,
                        # 1 second delay between reconnect
                        kwargs={"reconnect":1} )
                    websocket_app_thread.start()

                    while True:
                        result = open_sem.acquire( timeout=10 )
                        if result:
                            websocketOpenedCounter.inc( 1 )
                            return ws
                        else:
                            websocketOpenTimeout.inc( 1 )

            self._websocket = open_websocket()
            last_state = set()
            while True:
                # wait for a message
                self._has_event.acquire()

                current_state = None
                with self._state_mutex:
                    current_state = self._state.copy()

                removed_alerts = last_state - current_state
                added_alerts   = current_state - last_state

                def send_message( message ):
                    # TODO: validate message against schema
                    s = json.dumps( message )
                    self._websocket.send( s.encode( "ascii" ) )

                try:
                    for alert in removed_alerts:
                        send_message( {"disable": alert} )
                    for alert in added_alerts:
                        send_message( {"enable": alert} )

                    last_state = current_state

                except Exception as e:
                    # Let the websocket-client re-establish the connection for us
                    websocketSendIOExceptions.inc( 1 )
                    logging.exception( e )

        except Exception as e:
            logging.exception( e )
