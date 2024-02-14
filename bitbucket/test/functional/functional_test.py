import json
import unittest
import logging
import threading
import http
from http.server import BaseHTTPRequestHandler
from functools import partial

from simple_websocket_server import WebSocketServer, WebSocket

from process_context import find_free_port, managed_bitbucket
from container_context import managed_mongo

class WebSocketHandler( WebSocket ):
    def __init__( self, *args, **kwargs ):
        super().__init__(*args)
        self._callback = None
        if "callback" in kwargs:
            self._callback = kwargs["callback"]

    def handle( self ):
        try:
            data = json.loads(self.data)
            if self._callback is not None and "enable" in data:
                self._callback(data)
        except Exception as e:
            logging.exception(e)

class HTTPRequestHandler( BaseHTTPRequestHandler ):
    def do_GET( self ): # pylint: disable=invalid-name
        response = None
        status = 500
        headers = {}
        try:
            # TODO: the test should dictate which files are returned
            if self.path == "/2.0/user":
                with open( '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleUser.json',
                           'r',
                           encoding='ascii' ) as f:
                    logging.info( "returning sampleUser.json to %s", self.path )
                    # TODO: set response type to application/json
                    response = f.read()
                    status = 200
            elif self.path.startswith("/2.0/repositories/myworkspace/my-awesome-project/pipelines"):
                with open( '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleSingleFailurePipeline.json',
                           'r',
                           encoding='ascii' ) as f:
                    logging.info( "returning sampleSingleFailurePipeline.json to %s", self.path )
                    response = f.read()
                    status = 200

        except Exception as e:
            logging.exception( e )

        finally:
            self.send_response( status )
            for key, value in headers.items():
                self.send_header( key, value )
            self.end_headers()
            if response is not None:
                if isinstance( response, str ):
                    response = response.encode( "utf-8" )
                self.wfile.write( response )

class FunctionalTest( unittest.TestCase ):
    def test_functional( self ):
        ws_port: int = find_free_port()

        message = None
        message_sem = threading.Semaphore(0)
        def callback(m):
            nonlocal message
            message = m
            message_sem.release()

        def start_websocket_server():
            nonlocal callback
            try:
                handler = partial(WebSocketHandler, callback=callback)
                server = WebSocketServer( '0.0.0.0', ws_port, handler )
                server.serve_forever()
            except Exception as e:
                logging.exception( e )
        websocket_thread = threading.Thread( target=start_websocket_server, daemon=True )
        websocket_thread.start()

        bitbucket_port: int = find_free_port()
        def httpd_service():
            httpd = http.server.HTTPServer( ('', bitbucket_port), HTTPRequestHandler )
            httpd.serve_forever()
        httpd = threading.Thread( daemon=True, target=httpd_service )
        httpd.start()

        with managed_mongo() as mongo:
            with managed_bitbucket(config_file="/workspaces/blinkstick-notifier/bitbucket/test/functional/config.yml",
                                   led_controller_url=f"ws://127.0.0.1:{ws_port}",
                                   bitbucket_port=bitbucket_port,
                                   mongo_port=mongo.mongo_port):
                message_sem.acquire()

                self.assertEqual({"enable": "BitbucketBuildFailure"}, message)
