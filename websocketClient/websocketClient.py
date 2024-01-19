import json
import logging
import threading
import websocket

from threading import Lock, Semaphore

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
        'The number of times an on_message was called for the websocket, ostensibly the messages received on the websocket' )
websocketOnError = Counter(
        'websocketOnError',
        'The number of times an on_error was called for the websocket' )
websocketOnClose = Counter(
        'websocketOnClose',
        'The number of times an on_close was called for the websocket' )


class WebsocketClient( threading.Thread ):
    def __init__( self, url, name=None, httpPathPrefix=None, *args, **kwargs ):
        threading.Thread.__init__( self, daemon=True )
        self._websocketThread = None

        self._url = url
        self._stateMutex = Lock()
        self._state = set()
        self._hasEvent = Semaphore( 0 )
        self._name = name
        self._httpPathPrefix = httpPathPrefix

        self._websocket = None

    def __enter__( self ):
        self.start()
        return self

    def __exit__( self, *args ):
        self.stop()

    def enable( self, alert ):
        with self._stateMutex:
            self._state.add( alert )
        self._hasEvent.release()

    def disable( self, alert ):
        with self._stateMutex:
            if alert in self._state:
                self._state.remove( alert )
        self._hasEvent.release()

    def stop( self ):
        if self._websocket is not None:
            self._websocket.close()

    def run( self ):
        try:
            logger = logging.getLogger( __class__.__name__ )

            def openWebsocket():
                openSem = threading.Semaphore( 0 )
                def on_open( ws ):
                    try:
                        if self._name is not None:
                            m = { "name": self._name }
                            if self._httpPathPrefix is not None:
                                m["link"] = self._httpPathPrefix
                            ws.send( json.dumps( m ).encode( "ascii" ) )
                        with self._stateMutex:
                            for alert in self._state:
                                # TODO: use the same sendMessage as below. Logging in the one below
                                # isn't necessary duplicated here
                                # TODO: validate against schema
                                ws.send( json.dumps( { "enable": alert } ).encode( "ascii" ) )

                        openSem.release()

                    except Exception as e:
                        logger.exception( e )

                def on_message( ws, message ):
                    # This websocket will only receive responses. We can ignore them for the most part
                    websocketMessageReceived.inc( 1 )

                def on_error( ws, error ):
                    websocketOnError.inc( 1 )

                def on_close( ws, closeCode, closeMessage ):
                    websocketOnClose.inc( 1 )


                while True:
                    if self._websocketThread is not None:
                        # TODO: close the websocket if it hasn't been already closed
                        websocketThread.join()

                    websocketsOpenCounter.inc( 1 )
                    ws = websocket.WebSocketApp( self._url,
                                                 on_open=on_open,
                                                 on_message=on_message,
                                                 on_error=on_error,
                                                 on_close=on_close )
                    websocketAppThread = threading.Thread( target=ws.run_forever, kwargs={"reconnect":1} ) # 1 second delay between reconnect
                    websocketAppThread.start()

                    while True:
                        result = openSem.acquire( timeout=10 )
                        if result:
                            websocketOpenedCounter.inc( 1 )
                            return ws
                        else:
                            websocketOpenTimeout.inc( 1 )

            _websocket = openWebsocket()
            lastState = set()
            while True:
                # wait for a message
                self._hasEvent.acquire()

                currentState = None
                with self._stateMutex:
                    currentState = self._state.copy()

                removedAlerts = lastState - currentState
                addedAlerts   = currentState - lastState

                def sendMessage( message ):
                    # TODO: validate message against schema
                    s = json.dumps( message )
                    _websocket.send( s.encode( "ascii" ) )

                try:
                    for alert in removedAlerts:
                        sendMessage( {"disable": alert} )
                    for alert in addedAlerts:
                        sendMessage( {"enable": alert} )

                    lastState = currentState

                except Exception as e:
                    # Let the websocket-client re-establish the connection for us
                    websocketSendIOExceptions.inc( 1 )
                    logging.exception( e )

        except Exception as e:
            logging.exception( e )
