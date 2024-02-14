import unittest
import json

import webhook_listener

class WebhookTest( unittest.TestCase ) :
    def test_get_blinkstick_alert_for_prometheus_alert_default_event( self ):
        """ The reported alert does not exist in config.map and the blinkstick alert returned is
            the default event """
        hook = None
        with open('./webhook/test/unit/webhook_example.json', 'r', encoding='ascii') as f:
            hook = json.load(f)
        config = {"defaultEvent": "DefaultEvent"}
        self.assertEqual( webhook_listener.get_blinkstick_alert_for_prometheus_alert(config, hook), "DefaultEvent" )
