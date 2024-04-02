from http.server import SimpleHTTPRequestHandler
import unittest

from myblinkstick.application import Application

class MyApplication(Application):
    def __init__( self ): # pylint: disable=super-init-not-called
        pass
    def _get_httpd_handler(self) -> type[SimpleHTTPRequestHandler]:
        raise Exception()

class ApplicationTest(unittest.TestCase):
    def test_get_resource_file_contents__file_exists(self):
        application = MyApplication()
        with open(__file__, encoding='ascii') as f:
            self.assertEqual(f.read(), application._get_resource_file_contents(__file__)) # pylint: disable=protected-access
