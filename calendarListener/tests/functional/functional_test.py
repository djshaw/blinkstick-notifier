import unittest

from process_context import managed_calendar_listener

class FunctionalTest(unittest.TestCase):
    def test_functional(self):
        with managed_calendar_listener():
            # For the time being, it suffices that we get the prometheus up = 1.0 gauge
            pass
