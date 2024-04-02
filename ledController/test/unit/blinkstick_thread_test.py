import unittest
import logging

from blinkstickThread import BlinkstickThread, BlinkstickDTO

logging.basicConfig( level=logging.DEBUG )

class BlinkstickThreadTest( unittest.TestCase ):
    def test_empty( self ):
        """ Create and terminate the thread """
        thread = BlinkstickThread( config={"alerts": {}}, daemon=True )
        thread.start()

        self.assertEqual( [None, None, None, None, None, None, None, None], thread.get_visible_alerts() )
        self.assertEqual( [{},   {},   {},   {},   {},   {},   {},   {}  ], thread.get_current_alerts() )

        thread.terminate()
        thread.join()


    def test_enable_disable( self ):
        """ Turn an alert on and off. There should be no alerts after the alert is off. """
        alert = "Foo"

        thread = BlinkstickThread( config={ "alerts": [ { "name": alert, "channel": 0, "color": "blue" } ] }, daemon=True )
        thread.start()

        client_identifier = "me"

        blinkstick_api = BlinkstickDTO( thread, str(client_identifier) )

        blinkstick_api.enable( alert )
        self.assertEqual( [ { alert: {client_identifier} }, {}, {}, {}, {}, {}, {}, {} ],
                          thread.get_current_alerts() )

        blinkstick_api.disable( alert )
        alerts = thread.get_current_alerts()
        self.assertTrue( alert not in alerts or len( alerts[alert]) == 0 )

        thread.terminate()
        thread.join()


    def test_unregister( self ):
        """ When a client disconnects, all the client's alerts are removed """
        alert = "Foo"

        thread = BlinkstickThread( config={"alerts": [ { "name": alert, "channel": 0, "color": "blue" } ] }, daemon=True )
        thread.start()

        client_identifier = "me"
        blinkstick_api = BlinkstickDTO( thread, client_identifier )

        blinkstick_api.enable( alert )
        self.assertEqual( [ { alert: {client_identifier} }, {}, {}, {}, {}, {}, {}, {}],
                          thread.get_current_alerts() )
        blinkstick_api.unregister()

        self.assertEqual( [{}, {}, {}, {}, {}, {}, {}, {}], thread.get_current_alerts() )

        thread.terminate()
        thread.join()


    def test_alert_overridden_by_higher_priority_alert( self ):
        alert1 = "alert1"
        alert2 = "alert2"

        # alert1 has higher priority because it comes earlier in the array
        thread = BlinkstickThread( config={ "alerts": [ { "name": alert1, "channel": 0, "color": "blue" },
                                                        { "name": alert2, "channel": 0, "color": "red"  }] },
                                   daemon=True )
        thread.start()

        client_identifier = "me"

        blinkstick_api = BlinkstickDTO( thread, client_identifier )

        blinkstick_api.enable( alert2 )
        self.assertEqual( [alert2,                                 None, None, None, None, None, None, None],
                          thread.get_visible_alerts() )
        self.assertEqual( [{alert2: set( (client_identifier,) ) }, {},   {},   {},   {},   {},   {},   {}],
                          thread.get_current_alerts() )

        blinkstick_api.enable( alert1 )
        self.assertEqual( [{alert1: {client_identifier}, alert2: {client_identifier} },
                           {},
                           {},
                           {},
                           {},
                           {},
                           {},
                           {}], thread.get_current_alerts() )
        self.assertEqual( [alert1, None, None, None, None, None, None, None], thread.get_visible_alerts() )

        thread.terminate()
        thread.join()


    def test_two_alerts_on_separate_channels( self ):
        """ Two alerts can be enable concurrently, if the two alerts are on separate channels """
        alert1 = "alert1"
        alert2 = "alert2"

        # alert1 has higher priority because it comes earlier in the array
        thread = BlinkstickThread( config={ "alerts": [ { "name": alert1, "channel": 0, "color": "blue" },
                                                        { "name": alert2, "channel": 1, "color": "red"  }] },
                                   daemon=True )
        thread.start()

        client_identifier = "me"
        blinkstick_api = BlinkstickDTO( thread, client_identifier )

        blinkstick_api.enable( alert1 )
        blinkstick_api.enable( alert2 )

        self.assertEqual( [{alert1: {client_identifier}},
                           {alert2: {client_identifier}},
                           {},
                           {},
                           {},
                           {},
                           {},
                           {}], thread.get_current_alerts() )
        self.assertEqual( [alert1, alert2, None, None, None, None, None, None], thread.get_visible_alerts() )

        thread.terminate()
        thread.join()


    def test_disable_alert_that_was_never_enabled( self ):
        """ Disable an alert that was never enabled. As long as we don't crash, we should be fine. """
        alert = "Foo"
        thread = BlinkstickThread( config={"alerts": [{"name": alert, "channel": 0, "color": "blue"}]},
                                   daemon=True )
        thread.start()

        client_identifier = "me"
        blinkstick_api = BlinkstickDTO( thread, client_identifier )

        blinkstick_api.disable( alert )

        thread.terminate()
        thread.join()


    def test_enable_alert_that_has_no_configuration( self ):
        """ Enable an alert that has no configuration. The blinkstick thread should no-op and not crash. """
        thread = BlinkstickThread( config={"alerts": []},
                                   daemon=True )
        thread.start()

        client_identifier = "me"
        blinkstick_api = BlinkstickDTO( thread, client_identifier )

        blinkstick_api.enable( "Foo" )

        thread.terminate()
        thread.join()



    def test_disable_alert_that_has_no_configuration( self ):
        """ Disable an alert that has no configuration. The blinkstick thread should no-op and not crash. """
        thread = BlinkstickThread( config={"alerts": []},
                                   daemon=True )
        thread.start()

        client_identifier = "me"
        blinkstick_api = BlinkstickDTO( thread, client_identifier )

        blinkstick_api.disable( "Foo" )

        thread.terminate()
        thread.join()
