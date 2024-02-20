import unittest

from process_context import managed_outlook_listener

class FunctionalTest(unittest.TestCase):
    def test_functional(self):
        with managed_outlook_listener(credentials_file="outlookListener/test/credentials.yaml"):
            # For the time being, it suffices that we get the prometheus up = 1.0 gauge
            pass
