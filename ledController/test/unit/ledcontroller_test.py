import json
import os
import threading
import unittest
from unittest import mock
from unittest.mock import Mock

from ledController.src.ledController import WebSocketHandler

def get_schema_file(file) -> object:
    return get_json_file(os.path.join(os.path.dirname(__file__), '..', '..', 'src', file))

def get_json_file(file: str) -> object:
    with open(file, 'r', encoding='ascii') as f:
        return json.loads(f.read())

class LedControllerTest(unittest.TestCase):
    def test_invalid_message_received(self):
        server = {}
        address = "0.0.0.0"
        lock = threading.Lock()
        mock_blinkstick_thread = Mock(WebSocketHandler)
        clients = {}

        with mock.patch('socket.socket') as mock_socket:
            handler = WebSocketHandler(get_schema_file("receive.schema.json"),
                                       get_schema_file("send.schema.json"),
                                       mock_blinkstick_thread,
                                       address,
                                       lock,
                                       clients,
                                       server,
                                       mock_socket,
                                       address)
            handler.data = '{"foo": "bar"}'
            with self.assertLogs() as logs:
                handler.handle()
            self.assertRegex(
                logs.output[0],
                "ERROR:root:Error validating json: .* is not valid under any of the given schemas\n\n.*")
