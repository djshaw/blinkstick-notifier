import json
import logging
import socket
import threading
import time
import unittest

from contextlib import closing

from simple_websocket_server import WebSocketServer, WebSocket

from myblinkstick.websocket_client import WebsocketClient

logging.basicConfig( level=logging.DEBUG )
logging.getLogger( 'websocket' ).setLevel( logging.WARNING )

class WebsocketClientTest( unittest.TestCase ):
    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )


    class WebsocketServer( object ):
        def __init__( self, port, handle_fn=None ):
            self._port = port
            self._handle_fn = handle_fn
            self._server = None
            self._thread = None


        def __enter__( self ):
            def serve_forever( server ):
                try:
                    server.serve_forever()

                except Exception:
                    pass # Suppress the exception thrown when the socket is closed


            handle_fn = self._handle_fn
            class WebSocketHandler(WebSocket):
                def handle( self ):
                    try:
                        if callable( handle_fn ):
                            handle_fn( self.data )
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


    def get_port( self ):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(('', 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return s.getsockname()[1]


    def test_name( self ):
        """ Test that the name is automatically sent when the websocket connects """
        port = self.get_port()

        o = {}
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal sem

            o = json.loads( data )
            sem.release()

        name = "foo"
        with self.WebsocketServer( port, handle ), \
                WebsocketClient( f"ws://localhost:{port}", name=name ):

            sem.acquire(timeout=5)
            self.assertEqual( o, { 'name': name } )


    def test_enable_disable( self ):
        port = self.get_port()

        o = {}
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal sem

            o = json.loads( data )
            if "enable" in data:
                sem.release()

        with self.WebsocketServer( port, handle ), \
             WebsocketClient( f"ws://localhost:{port}" ) as websocket_client:
            alert_name = "foo"

            websocket_client.enable( alert_name )

            sem.acquire(timeout=5)
            self.assertEqual( { 'enable': alert_name }, o )

            # There's a race somewhere. If we exit too soon, an exception is raised: "RuntimeError:
            # dictionary changed size during iteration." Sleep here to prevent that exception.
            time.sleep( 1 )


    def test_client_starts_first( self ):
        """ The client starts first, and sets its state. Then a connection is established on the
            server. Verify that the client sends the state when it connects to the server
        """
        port = self.get_port()

        with WebsocketClient( f"ws://localhost:{port}" ) as websocket_client:
            alert_name = "foo"
            websocket_client.enable( alert_name )

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

            with self.WebsocketServer( port, handle ):
                sem.acquire(timeout=5)
                self.assertEqual( { 'enable': alert_name }, o )


    def test_server_hiccup( self ):
        port = self.get_port()

        o = {}
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal sem

            o = json.loads( data )
            if "enable" in data:
                sem.release()


        with self.WebsocketServer( port, handle ) as server, \
             WebsocketClient( f"ws://localhost:{port}" ) as websocket_client:
            alert_name = "foo"

            websocket_client.enable( alert_name )
            sem.acquire(timeout=5)
            o = {}

            server.__exit__()
            server.__enter__()

            sem.acquire(timeout=5)

            self.assertEqual( { 'enable': alert_name }, o )

        time.sleep( 1 )


    def test_disable_clears_state( self ):
        port = self.get_port()

        o = {}
        ready_sem = threading.Semaphore( 0 )
        sem = threading.Semaphore( 0 )

        def handle( data ):
            nonlocal o
            nonlocal ready_sem
            nonlocal sem

            ready_sem.acquire()

            o = json.loads( data )
            if "enable" in data:
                sem.release()


        with WebsocketClient( f"ws://localhost:{port}" ) as websocket_client:

            # The client will immediately try to send a message even though it hasn't connected to
            # the server yet. Send a sacrificial message first
            sacrificial_name = "asdf"
            websocket_client.enable( sacrificial_name )

            alert_name = "foo"
            websocket_client.enable( alert_name )
            websocket_client.disable( alert_name )

            time.sleep( 1 )

            with self.WebsocketServer( port, handle ):
                o = {}
                ready_sem.release()
                sem.acquire(timeout=2)
                self.assertEqual( { 'enable': sacrificial_name }, o )

                # TODO:  { 'enable': sacrificialname } is sent twice. Once when the connection is
                # established. Once when for when _hasEvent is processed.
                o = {}
                ready_sem.release()
                sem.acquire(timeout=2)
                self.assertEqual( { 'enable': sacrificial_name}, o )

                o = {}
                ready_sem.release()
                sem.acquire(timeout=2)
                self.assertEqual( {}, o )

        time.sleep( 1 )


    def test_disable_without_enable( self ):
        port = self.get_port()

        with WebsocketClient( f"ws://localhost:{port}" ) as websocket_client:
            websocket_client.disable( "foo" )


if __name__ == "__main__":
    unittest.main()
