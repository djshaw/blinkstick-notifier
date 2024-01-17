import json
import logging
import socket
import threading
import time
import unittest

from contextlib import closing

from simple_websocket_server import WebSocketServer, WebSocket

from websocketClient import WebsocketClient

logging.basicConfig( level=logging.DEBUG )
logging.getLogger( 'websocket' ).setLevel( logging.WARNING )

class WebsocketClientTest( unittest.TestCase ):
    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )


    class websocketServer( object ):
        def __init__( self, port, handleFn=None ):
            self._port = port
            self._handleFn = handleFn
            self._server = None
            self._thread = None


        def __enter__( self ):
            def serve_forever( server ):
                try:
                    server.serve_forever()

                except Exception as e:
                    pass # Suppress the exception thrown when the socket is closed


            handleFn = self._handleFn
            class WebSocketHandler(WebSocket):
                def handle( self ):
                    try:
                        if callable( handleFn ):
                            handleFn( self.data )
                    except Exception as e:
                        logging.exception( e )

                def connected( self ):
                    pass

                def handle_close( self ):
                    pass

            self._server = WebSocketServer('0.0.0.0', self._port, WebSocketHandler )
            self._thread = threading.Thread( target=serve_forever, args=(self._server,), daemon=True )
            self._thread.start()

            return self


        def __exit__( self, *args ):
            if self._server is not None:
                self._server.close()

            if self._thread is not None:
                self._thread.join()


    def getPort( self ):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(('', 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return s.getsockname()[1]


    def testName( self ):
        """ Test that the name is automatically sent when the websocket connects """
        port = self.getPort()

        o = {}
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal sem

            o = json.loads( data )
            sem.release()

        name = "foo"
        with self.websocketServer( port, handle ), \
                WebsocketClient( "ws://localhost:%d" % port, name=name ) as websocketClient:

            sem.acquire(timeout=5)
            self.assertEqual( o, { 'name': name } )


    def testEnableDisable( self ):
        port = self.getPort()

        o = {}
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal sem

            o = json.loads( data )
            if "enable" in data:
                sem.release()

        with self.websocketServer( port, handle ), \
             WebsocketClient( "ws://localhost:%d" % port ) as websocketClient:
            alertName = "foo"

            websocketClient.enable( alertName )

            sem.acquire(timeout=5)
            self.assertEqual( { 'enable': alertName }, o )

            # There's a race somewhere. If we exit too soon, an exception is raised: "RuntimeError:
            # dictionary changed size during iteration." Sleep here to prevent that exception.
            time.sleep( 1 )


    def testClientStartsFirst( self ):
        """ The client starts first, and sets its state. Then a connection is established on the
            server. Verify that the client sends the state when it connects to the server
        """
        port = self.getPort()

        with WebsocketClient( "ws://localhost:%d" % port) as websocketClient:
            alertName = "foo"
            websocketClient.enable( alertName )

            # Let some time pass before starting the server
            time.sleep( 1 )

            o = {}
            sem = threading.Semaphore( 0 )
            def handle( data ):
                nonlocal o
                nonlocal sem

                o = json.loads( data )
                if "enable" in data:
                    sem.release()

            with self.websocketServer( port, handle ):
                sem.acquire(timeout=5)
                self.assertEqual( { 'enable': alertName }, o )


    def testServerHiccup( self ):
        port = self.getPort()

        o = {}
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal sem

            o = json.loads( data )
            if "enable" in data:
                sem.release()


        with self.websocketServer( port, handle ) as server, \
             WebsocketClient( "ws://localhost:%d" % port ) as websocketClient:
            alertName = "foo"

            websocketClient.enable( alertName )
            sem.acquire(timeout=5)
            o = {}

            server.__exit__()
            server.__enter__()

            sem.acquire(timeout=5)

            self.assertEqual( { 'enable': alertName }, o )

        time.sleep( 1 )


    def testDisableClearsState( self ):
        port = self.getPort()

        o = {}
        readyToHandle = threading.Semaphore( 0 )
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal readyToHandle
            nonlocal sem

            readyToHandle.acquire()

            o = json.loads( data )
            if "enable" in data:
                sem.release()


        with WebsocketClient( "ws://localhost:%d" % port ) as websocketClient:

            # The client will immediately try to send a message even though it hasn't connected to
            # the server yet. Send a sacrificial message first
            sacrificialName = "asdf"
            websocketClient.enable( sacrificialName )

            alertName = "foo"
            websocketClient.enable( alertName )
            websocketClient.disable( alertName )

            time.sleep( 1 )

            with self.websocketServer( port, handle ) as server:
                o = {}
                readyToHandle.release()
                sem.acquire(timeout=2)
                self.assertEqual( { 'enable': sacrificialName }, o )

                # TODO:  { 'enable': sacrificialname } is sent twice. Once when the connection is
                # established. Once when for when _hasEvent is processed.
                o = {}
                readyToHandle.release()
                sem.acquire(timeout=2)
                self.assertEqual( { 'enable': sacrificialName}, o )

                o = {}
                readyToHandle.release()
                sem.acquire(timeout=2)
                self.assertEqual( {}, o )

        time.sleep( 1 )


    def testDisableWithoutEnable( self ):
        port = self.getPort()

        def handle( data ):
            # No data should make it to the server
            self.failure()

        with WebsocketClient( "ws://localhost:%d" % port ) as websocketClient:
            websocketClient.disable( "foo" )


if __name__ == "__main__":
    unittest.main()

