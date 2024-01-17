from __future__ import print_function

import datetime
import http
import json
import logging
import os
import queue
import re
import signal
import sys
import threading
import time
import urllib
import yaml

from threading import Lock

from navbar import Navbar
from websocketClient import WebsocketClient
from workunit import WorkQueue, Workunit, installWorkunitsCollector

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from prometheus_client import start_http_server, Gauge
from prometheus_client.core import REGISTRY

logging.basicConfig( level=logging.DEBUG )
logging.getLogger( 'googleapiclient.discovery_cache' ).setLevel( logging.ERROR )

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

up =    Gauge(
        'up',
        'Whether or not the calendarListener is running' )
up.set( 0 )

credentialsInvalid = Gauge(
        'credentialsInvalid',
        'Indicates whether or not the credentials are invalid',
        ['calendar'] )
credentialsExpired = Gauge(
        'credentailsExpired',
        'Indicates whether or not the credentials are expired',
        ['calendar'] )
workunitExceptions = Gauge(
        'workunitExceptions',
        'The number of exceptions caused by work units for a particular calendar',
        ['calendar'] )
# TODO: state (i.e. sleeping or executing work unit)
# TODO: time to next work unit
# TODO: polling time (as samples)


def updateValidExpiredMetrics( calendar, credentials ):
    credentialsInvalid.labels( calendar["name"] ).set( 1 if not credentials or not credentials.valid else 0 )
    credentialsExpired.labels( calendar["name"] ).set( 1 if credentials is not None and credentials.expired else 0 )


from prometheus_client.core import GaugeMetricFamily
from typing import Iterable
from prometheus_client.metrics_core import Metric
class CustomCollector( object ):
    def collect( self ) -> Iterable[Metric]:
        return [
            GaugeMetricFamily(
                'python_threads',
                'The number of threads reported by python\'s threading.active_count()',
                value=threading.active_count())]

REGISTRY.register( CustomCollector() )


def getTokenFileName( calendar ):
    return os.path.join( tokensDirectory, calendar["name"] + ".token.json" )


def refreshCredentials( calendar, credentials ):
    updateValidExpiredMetrics( calendar, credentials )
    refreshed = False
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh( Request() )
        refreshed = True

    f = getTokenFileName( calendar )
    # TODO: instead of checking if filesize is different, check to see if content is different
    if credentials and ( refreshed or not os.path.exists( f ) or os.stat( f ).st_size == 0 ):
        with open( f, 'w' ) as token:
            token.write( credentials.to_json() )

ISO_DATE_PATTERN = re.compile("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[+-]\\d{4}")

lock = threading.Lock()
config = None
state = {}
tokensMap = {}

def pollCalendar( calendar, credentials ):
    global config

    logging.info( "polling calendar " + calendar["name"] )

    # TODO: precalculate this value
    calendars = list( map( lambda x: x["name"], config ) )

    refreshCredentials( calendar, credentials )

    updateValidExpiredMetrics( calendar, credentials )

    result = []

    now = datetime.datetime.now()

    if credentials and credentials.valid:
        # TODO: only rebuild the service if the credentials change (a loop in a loop?)
        service = build( 'calendar', 'v3', credentials=credentials )
        now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time

        for c in service.calendarList().list().execute().get('items'):
            if c["summary"] not in calendars and ("primary" not in c or not c["primary"]):
                logging.debug("skipping calendar " + c["summary"])
                continue

            events_result = service.events().list(calendarId=c["id"],
                                                  timeMin=now, # This will include events
                                                               # that have already started
                                                  maxResults=10, # TODO: this can be 1?
                                                  singleEvents=True, # TODO: what about repeated events!
                                                  orderBy='startTime').execute()
            events = events_result.get( 'items', [] )

            # Prints the start and name of the next 10 events
            for event in events:
                localNow = datetime.datetime.now( datetime.timezone.utc ).astimezone()

                startTime = event['start'].get( 'dateTime', event['start'].get( 'date' ) )[::-1].replace( ":", "", 1 )[::-1]
                # All day events have a start time of YYYY-mm-dd
                if ISO_DATE_PATTERN.match( startTime ) == None:
                    logging.debug("skipping " + startTime)
                    continue

                startTime = datetime.datetime.strptime(
                    startTime,
                    "%Y-%m-%dT%H:%M:%S%z" )

                endTime = event['end'].get( 'dateTime', event['end'].get( 'date' ) )[::-1].replace( ":", "", 1 )[::-1]
                endTime = datetime.datetime.strptime(
                    endTime,
                    "%Y-%m-%dT%H:%M:%S%z" )
                delta = startTime - localNow

                if ( startTime - localNow ).total_seconds() < 0 and \
                   ( endTime - localNow ).total_seconds() > 0:
                       logging.info( "Current event: " + event["summary"] )
                       result.append( event )

    return result


class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
    def do_GET( self ):
        global config
        global lock
        global tokensMap

        response = None
        status = 500
        headers = {}

        try:
            response = ""

            parse = urllib.parse.urlparse( self.path )
            query = urllib.parse.parse_qs( parse.query )
            # Requires the Authorized JavaScript origins set to http://localhost:8080
            #              Authorized redirect URIs      set to http://localhost:8080/calendarListener
            if "code" in query and \
               "scope" in query and \
               "state" in query:
                flow = InstalledAppFlow.from_client_secrets_file(
                        credentialsFile, SCOPES, redirect_uri="http://localhost:8080" + httpPathPrefix )
                flow.fetch_token( code=query["code"][0] )
                token=flow.credentials

                calendar = list( filter( lambda c: c["name"] == query["state"][0], config ) )[0]
                refreshCredentials( calendar, token )

                with lock:
                    tokensMap[calendar["name"]] = token

                status = 302
                headers["Location"] = httpPathPrefix + "/"

            elif self.path.startswith( httpPathPrefix + "/flow?" ):
                calendar = self.path[len( httpPathPrefix + "/flow?" ):]

                flowPort = 8081
                flow = InstalledAppFlow.from_client_secrets_file(
                        credentialsFile, SCOPES, redirect_uri="http://localhost:8080" + httpPathPrefix )
                authUrl, _ = flow.authorization_url(
                        access_type="offline",
                        prompt='consent',
                        state=calendar )

                status = 302
                headers = { "Location": authUrl }

            elif self.path.startswith( httpPathPrefix ): # TODO: better to do a refex match? (or normalize to either always include or always not have the trailing "/"?)
                # TODO: report the current time (including timezone)!
                response += """
                    <html>
                        <head>
                        <link rel="stylesheet"
                              href="https://cdn.jsdelivr.net/npm/bootstrap@4.0.0/dist/css/bootstrap.min.css"
                              integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm"
                              crossorigin="anonymous">
                            <script src="https://code.jquery.com/jquery-3.2.1.slim.min.js" integrity="sha384-KJ3o2DKtIkvYIK3UENzmM7KCkRr/rE9/Qpg6aAZGJwFDMVNA/GpGFF93hXpG5KkN" crossorigin="anonymous"></script>
                            <script src="https://cdn.jsdelivr.net/npm/popper.js@1.12.9/dist/umd/popper.min.js" integrity="sha384-ApNbgh9B+Y1QKtv3Rn7W3mgPxhU9K/ScQsAP7hUibX39j7fakFPskvXusvfa0b4Q" crossorigin="anonymous"></script>
                            <script src="https://cdn.jsdelivr.net/npm/bootstrap@4.0.0/dist/js/bootstrap.min.js" integrity="sha384-JZR6Spejh4U02d8jOt6vLEHfe/JQGiRRSQQxSfFWpi1MquVdAyjUar5+76PVCmYl" crossorigin="anonymous"></script>
                        </head>
                        <body>
                        """ \
                        + Navbar().render() \
                        + """
                            <h3>Calendars</h3>
                            <table class="table">
                                <tbody>"""

                for key, token in tokensMap.items():
                    response += "<tr><td>" + key + "</td>" + \
                                "<td>(" + ("not " if not token or not token.valid else "") + "valid)</td>" + \
                                "<td><a href='" + httpPathPrefix + "/flow?" + key + "'>link</a></td>"
                    # TODO: report which calendar event is current, if any


                # TODO: include configuration
                with lock:
                    response += """
                                    </tbody>
                                </table>
                                <h3>Configuration</h3>
                                <pre class="bg-light">""" + \
                                yaml.dump( config,
                                           sort_keys=True,
                                           indent=2 ) + \
                                """</pre>
                            </body>
                        </html>
                    """
                status = 200


            elif self.path.startswith( httpPathPrefix + "/oauth2callback?" ):
                flow.fetch_token( authorization_response=authorization_response )

        finally:
            self.send_response( status )
            for key in headers:
                self.send_header( key, headers[key] )
            self.end_headers()
            if response != None:
                if type( response ) is str:
                    response = response.encode( "utf-8" )
                self.wfile.write( response )





configFile =      os.environ["CONFIG_FILE"]      if "CONFIG_FILE"      in os.environ else "config.yml"
tokensDirectory = os.environ["TOKENS_DIRECTORY"] if "TOKENS_DIRECTORY" in os.environ else "/tokens"
credentialsFile = os.environ["CREDENTIALS_FILE"] if "CREDENTIALS_FILE" in os.environ else "credentials.json"
httpPathPrefix  = os.environ["HTTP_PATH_PREFIX"] if "HTTP_PATH_PREFIX" in os.environ else "/calendarListener"


def signalHandler( signum, frame ):
    if signum == signal.SIGINT or signum == signal.SIGTERM:
        # TODO: shouldn't need this
        sys.exit( 0 )

class CalendarWorkunit( Workunit ):
    def __init__( self, ws, dt, calendar ):
        self._ws = ws
        self._calendar = calendar
        super().__init__( dt )

    def work( self ):
        global lock
        global state
        global tokensMap
        global workqueue

        calendarName = self._calendar["name"]
        try:
            credentials = None
            with lock:
                credentials = tokensMap[calendarName]
                oldState = state[calendarName] if calendarName in state else []

            newState = pollCalendar( self._calendar, credentials )
            if newState != oldState:
                if len( oldState ) == 0:
                    self._ws.enable( self._calendar["notification"] )

                elif len( newState ) == 0:
                    self._ws.disable( self._calendar["notification"] )

            with lock:
                state[calendarName] = newState

        except Exception as e:
            logging.exception( e )
            workunitExceptions.labels( calendarName ).inc( 1 )

        finally:
            future = datetime.datetime.now() + datetime.timedelta( seconds=60 )
            workqueue.enqueue( CalendarWorkunit( self._ws, future, self._calendar ) )


workqueue = None

def main():
    global workqueue
    global config

    signal.signal( signal.SIGINT,  signalHandler )
    signal.signal( signal.SIGTERM, signalHandler )

    config = None
    if os.path.exists( configFile ):
        with open( configFile, 'r' ) as f:
            config = yaml.safe_load( f )

    else:
        logging.warning( "Warning: using an empty config" )
        config = []

    # TODO: verify that httpPathPrefix starts with "/"

    # start prometheus
    start_http_server( 9000 )

    ws = WebsocketClient( "ws://led-controller:9099",
                          name="CalendarListener",
                          httpPathPrefix=httpPathPrefix )
    ws.start()

    logging.debug( "have websocket connection" )

    # start the credentails web service thing

    def httpdService():
        # TODO: make port configurable
        httpd = http.server.HTTPServer( ('', 8080), HTTPRequestHandler )
        httpd.serve_forever()
    httpd = threading.Thread( target=httpdService, daemon=None )
    httpd.start()

    workqueue = WorkQueue()
    installWorkunitsCollector( workqueue )

    for calendar in config:
        try:
            workunitExceptions.labels( calendar["name"] ).set( 0 )

            tokensMap[calendar["name"]] = None
            state[calendar["name"]] = []

            workqueue.enqueue( CalendarWorkunit( ws, datetime.datetime.now(), calendar ) )

            f = getTokenFileName( calendar )
            if os.path.exists( f ):
                credentials = Credentials.from_authorized_user_file( f, SCOPES )
                if credentials:
                    # Need to refresh the token because credentials.valid initializes to False
                    refreshCredentials( calendar, credentials )
                tokensMap[calendar["name"]] = credentials
                updateValidExpiredMetrics( calendar, credentials )

        except Exception as e:
            # Catch the exception and continue. Hopefully, we'll be able to proceed on other calendars.
            logging.exception( e )

    workqueue.start()
    up.set( 1 )

    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.

    # TODO: don't busy wait. Use a semaphore. If we finish the main thread, we're
    # not allowed to allocate new ones
    while True:
        time.sleep( 10 )


if __name__ == '__main__':
    logging.info( "starting..." )
    main()

