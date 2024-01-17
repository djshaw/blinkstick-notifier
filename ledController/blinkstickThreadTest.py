import unittest
import logging

from blinkstickThread import BlinkstickThread, BlinkstickDTO

logging.basicConfig( level=logging.DEBUG )

class BlinkstickThreadTest( unittest.TestCase ):
    def testEmpty( self ):
        """ Create and terminate the thread """
        thread = BlinkstickThread( config={}, daemon=True )
        thread.start()

        self.assertEqual( [None, None, None, None, None, None, None, None], thread.getVisibleAlerts() )
        self.assertEqual( [{},   {},   {},   {},   {},   {},   {},   {}  ], thread.getCurrentAlerts() )

        thread.terminate()
        thread.join()


    def testEnableDisable( self ):
        """ Turn an alert on and off. There should be no alerts after the alert is off. """
        alert = "Foo"

        thread = BlinkstickThread( config=[ { "name": alert, "channel": 0, "color": "blue" } ], daemon=True )
        thread.start()

        clientIdentifier = ("me",)

        blinkstickApi = BlinkstickDTO( thread, clientIdentifier )

        blinkstickApi.enable( alert )
        self.assertEqual( [ { alert: set( (clientIdentifier,) ) }, {}, {}, {}, {}, {}, {}, {} ], thread.getCurrentAlerts() )

        blinkstickApi.disable( alert )
        alerts = thread.getCurrentAlerts()
        self.assertTrue( alert not in alerts or len( alerts[alert]) == 0 )

        thread.terminate()
        thread.join()


    def testUnregister( self ):
        """ When a client disconnects, all the client's alerts are removed """
        alert = "Foo"

        thread = BlinkstickThread( config=[ { "name": alert, "channel": 0, "color": "blue" } ], daemon=True )
        thread.start()

        clientIdentifier = ("me",)

        blinkstickApi = BlinkstickDTO( thread, clientIdentifier )

        blinkstickApi.enable( alert )
        self.assertEqual( [ { alert: set( (clientIdentifier,) ) }, {}, {}, {}, {}, {}, {}, {}], thread.getCurrentAlerts() )
        blinkstickApi.unregister()

        self.assertEqual( [{}, {}, {}, {}, {}, {}, {}, {}], thread.getCurrentAlerts() )

        thread.terminate()
        thread.join()


    def testAlertOverriddenByHigherPriorityAlert( self ):
        alert1 = "alert1"
        alert2 = "alert2"

        thread = BlinkstickThread( config=[ { "name": alert1, "channel": 0, "color": "blue" },  # alert1 has higher priority because
                                                                                                # it comes earlier in the array
                                            { "name": alert2, "channel": 0, "color": "red"  }],
                                   daemon=True )
        thread.start()

        clientIdentifier = ("me",)

        blinkstickApi = BlinkstickDTO( thread, clientIdentifier )

        blinkstickApi.enable( alert2 )
        self.assertEqual( [alert2,                                None, None, None, None, None, None, None], thread.getVisibleAlerts() )
        self.assertEqual( [{alert2: set( (clientIdentifier,) ) }, {},   {},   {},   {},   {},   {},   {}],   thread.getCurrentAlerts() )

        blinkstickApi.enable( alert1 )
        self.assertEqual( [{alert1: set( (clientIdentifier,) ), alert2: set( (clientIdentifier,) ) },
                           {},
                           {},
                           {},
                           {},
                           {},
                           {},
                           {}], thread.getCurrentAlerts() )
        self.assertEqual( [alert1,                None, None, None, None, None, None, None], thread.getVisibleAlerts() )

        thread.terminate()
        thread.join()


    def _testTwoAlertsOnSeparateChannels( self ):
        """ Two alerts can be enable concurrently, if the two alerts are on separate channels """
        alert1 = "alert1"
        alert2 = "alert2"

        thread = BlinkstickThread( config=[ { "name": alert1, "channel": 0, "color": "blue" },  # alert1 has higher priority because
                                                                                                # it comes earlier in the array
                                            { "name": alert2, "channel": 1, "color": "red"  }],
                                   daemon=True )
        thread.start()

        clientIdentifier = ("me",)
        blinkstickApi = BlinkstickDTO( thread, clientIdentifier )

        blinkstickApi.enable( alert1 )
        blinkstickApi.enable( alert2 )

        self.assertEqual( [{alert1: set( (clientIdentifier,) )},
                           {alert2: set( (clientIdentifier,) )},
                           {},
                           {},
                           {},
                           {},
                           {},
                           {}], thread.getCurrentAlerts() )
        self.assertEqual( [alert1, alert2, None, None, None, None, None, None], thread.getVisibleAlerts() )

        thread.terminate()
        thread.join()


    def testDisableAlertThatWasNeverEnabled( self ):
        """ Disable an alert that was never enabled. As long as we don't crash, we should be fine. """
        alert = "Foo"
        thread = BlinkstickThread( config=[{"name": alert, "channel": 0, "color": "blue"}],
                                   daemon=True )
        thread.start()

        clientIdentifier = ("me",)
        blinkstickApi = BlinkstickDTO( thread, clientIdentifier )

        blinkstickApi.disable( alert )

        thread.terminate()
        thread.join()


    def testEnableAlertThatHasNoConfiguration( self ):
        """ Enable an alert that has no configuration. The blinkstick thread should no-op and not crash. """
        thread = BlinkstickThread( config=[],
                                   daemon=True )
        thread.start()

        clientIdentifier = ("me",)
        blinkstickApi = BlinkstickDTO( thread, clientIdentifier )

        blinkstickApi.enable( "Foo" )

        thread.terminate()
        thread.join()



    def testDisableAlertThatHasNoConfiguration( self ):
        """ Disable an alert that has no configuration. The blinkstick thread should no-op and not crash. """
        thread = BlinkstickThread( config=[],
                                   daemon=True )
        thread.start()

        clientIdentifier = ("me",)
        blinkstickApi = BlinkstickDTO( thread, clientIdentifier )

        blinkstickApi.disable( "Foo" )

        thread.terminate()
        thread.join()


if __name__ == "__main__":
    unittest.main()

