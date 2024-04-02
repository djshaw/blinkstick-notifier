from contextlib import contextmanager
from functools import partial
import json
import logging
from queue import Queue
import threading
from typing import Any, Generator

from simple_websocket_server import WebSocket, WebSocketServer
from process_context import find_free_port

class WebSocketHandler( WebSocket ):
    def __init__( self, *args, **kwargs ):
        super().__init__(*args)
        self._callback = None
        if "callback" in kwargs:
            self._callback = kwargs["callback"]

    def handle( self ):
        try:
            if isinstance(self.data, str):
                data = json.loads(self.data)
                if self._callback is not None and "enable" in data:
                    self._callback(data)
        except Exception as e:
            logging.exception(e)


class MockLedController():
    def __init__(self, ws_port: int, queue: Queue):
        self.ws_port = ws_port
        self.queue = queue


@contextmanager
def managed_mock_ledcontroller_context(ws_port: int | None = None) -> Generator[MockLedController, Any, None]:
    if ws_port is None:
        ws_port = find_free_port()

    messages = Queue()

    def start_websocket_server():
        def callback(m):
            messages.put(m)
        try:
            handler = partial(WebSocketHandler, callback=callback)
            server = WebSocketServer( '0.0.0.0', ws_port, handler )
            server.serve_forever()
        except Exception as e:
            logging.exception( e )
    websocket_thread = threading.Thread( target=start_websocket_server, daemon=True )
    websocket_thread.start()

    yield MockLedController(ws_port, messages)

    # TODO: need a way to kill the mock websocket server!
