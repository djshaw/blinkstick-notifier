import unittest

import requests

from process_context import managed_calendar_listener

class FunctionalTest(unittest.TestCase):
    def test_functional(self):
        with managed_calendar_listener("ws://127.0.0.1:9999",
                                       "calendarListener/tests/config.yml") as calendar_listener:
            request = requests.get(f"http://127.0.0.1:{calendar_listener.http_port}/calendarListener", timeout=5)
            self.assertEqual(200, request.status_code)
