import queue
from typing import override
import unittest
import threading
import logging
import json
from functools import partial

import requests
from simple_websocket_server import WebSocketServer, WebSocket

from process_context import find_free_port, managed_webhook

class WebSocketHandler( WebSocket ):
    def __init__( self, *args, **kwargs ):
        super().__init__(*args)
        self._callback = None
        if "callback" in kwargs:
            self._callback = kwargs["callback"]

    def connected(self):
        print("connected")
        return super().connected()
    def handle_close(self):
        print("close")
        return super().handle_close()
    @override
    def handle( self ):
        try:
            if isinstance(self.data, str):
                data = json.loads(self.data)
                if self._callback is not None and "enable" in data:
                    self._callback(data)
        except Exception as e:
            logging.exception(e)

class WebhookFunctionalTest( unittest.TestCase ):
    def test_functional(self):
        message_queue = queue.Queue()
        def callback(message):
            nonlocal message_queue
            message_queue.put(message)

        ws_port: int=find_free_port()
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
        with managed_webhook(f"ws://127.0.0.1:{ws_port}",
                             "./webhook/test/functional/config.yml") as webhook:
            data = None
            with open("./webhook/test/functional/webhook_example.json", 'r', encoding='ascii') as f:
                data = json.load(f)
            response = requests.post(f"http://127.0.0.1:{webhook.http_port}/", json=data, timeout=500)
            self.assertEqual(200, response.status_code)

            message = message_queue.get()

            # TODO: verify that `python_threads` is in the metrics/ output
            self.assertEqual({"enable":"AlertManagerAlert"}, message)

            # Verify that we can still get the status page
            response = requests.get(f"http://127.0.0.1:{webhook.http_port}/webhook", timeout=5)
            self.assertEqual(200, response.status_code)
