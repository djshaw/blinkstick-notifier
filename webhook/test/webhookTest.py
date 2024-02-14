import json
import os
import unittest
import logging

from webhook import getBlinkstickAlertForPrometheusAlert

logging.basicConfig( level=logging.DEBUG )

class GetBlinkstickAlertForPrometheusTest( unittest.TestCase ):
    # TODO: these tests rely on the production config.yaml, which I think is a bad assumption for tests
    def testSingleSet( self ):
        data = None
        with open( os.path.join( os.path.dirname( __file__ ), "sampleSetMessage.json" ) ) as f:
            data = json.load( f )

        self.assertEqual( "PersonalCalendarError", getBlinkstickAlertForPrometheusAlert( data["alerts"][0] ) )

    def testMultiSet( self ):
        data = None
        with open( os.path.join( os.path.dirname( __file__ ), "sampleMultiSetMessage.json" ) ) as f:
            data = json.load( f )

        self.assertEqual( "PersonalCalendarError", getBlinkstickAlertForPrometheusAlert( data["alerts"][0] ) )
        self.assertEqual( "WorkCalendarError", getBlinkstickAlertForPrometheusAlert( data["alerts"][1] ) )

if __name__ == "__main__":
    unittest.main()
