import datetime
import unittest
import json
import sys

from googleapiclient.http import HttpMock, HttpMockSequence, RequestMockBuilder
from googleapiclient.discovery import build

class CalendarListenerTest( unittest.TestCase ):
    def testPollEmptyCalendar( self ):
        http = HttpMockSequence([
            # TODO: I really thought the first response would be the calendar-discovery.json response
            ({'status': '200'}, open("/app/tests/calendar-empty.json").read())])
        api_key = 'your_api_key'
        service = build('calendar', 'v3',
                        http=http,
                        developerKey="blah")
        request = service.events().list( calendarId="id",
                                         maxResults=10,
                                         singleEvents=True,
                                         orderBy="startTime" )
        response = request.execute()
        print( "events response" + str( response ) )
        events = response.get( 'items', [] )
        print( events[0] )

if __name__ == "__main__":
    unittest.main()

