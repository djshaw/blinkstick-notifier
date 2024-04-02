import unittest

import requests

from process_context import managed_outlook_listener

class FunctionalTest(unittest.TestCase):
    def test_functional(self):
        with managed_outlook_listener('outlookListener/test/config.yml',
                                      credentials_file="outlookListener/test/credentials.yaml") as outlook_listener:
            request = requests.get(f"http://127.0.0.1:{outlook_listener.http_port}/outlookListener", timeout=5)
            self.assertEqual(200, request.status_code)
