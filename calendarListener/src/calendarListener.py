from __future__ import print_function

import datetime
import http
import logging
import os
import re
import sys
import threading
from typing import override
import urllib
import yaml

from myblinkstick.navbar import Navbar
from myblinkstick.application import Sensor
from myblinkstick.workqueue import Workunit

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from prometheus_client import Gauge

logging.getLogger( 'googleapiclient.discovery_cache' ).setLevel( logging.ERROR )

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

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


def update_valid_expired_metrics( calendar, credentials ):
    credentialsInvalid.labels( calendar["name"] ).set( 1 if not credentials or not credentials.valid else 0 )
    credentialsExpired.labels( calendar["name"] ).set( 1 if credentials is not None and credentials.expired else 0 )


def get_token_filename( calendar ):
    return os.path.join( tokensDirectory, calendar["name"] + ".token.json" )


def refresh_credentials( calendar, credentials ):
    update_valid_expired_metrics( calendar, credentials )
    refreshed = False
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh( Request() )
        refreshed = True

    f = get_token_filename( calendar )
    # TODO: instead of checking if filesize is different, check to see if content is different
    if credentials and ( refreshed or not os.path.exists( f ) or os.stat( f ).st_size == 0 ):
        with open( f, 'w', encoding='ascii' ) as token:
            token.write( credentials.to_json() )

ISO_DATE_PATTERN = re.compile("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[+-]\\d{4}")

tokensDirectory = os.environ["TOKENS_DIRECTORY"] if "TOKENS_DIRECTORY" in os.environ else "/tokens"
# TODO: make this a configuration option
credentialsFile = os.environ["CREDENTIALS_FILE"] if "CREDENTIALS_FILE" in os.environ else "credentials.json"
httpPathPrefix  = os.environ["HTTP_PATH_PREFIX"] if "HTTP_PATH_PREFIX" in os.environ else "/calendarListener"


class CalendarWorkunit( Workunit ):
    def __init__( self, config, ws, dt, calendar, workqueue, tokens_map_lock: threading.Lock, tokens_map, state ):
        super().__init__( dt )
        self._config = config
        self._ws = ws
        self._calendar = calendar
        self._workqueue = workqueue
        self._tokens_map_lock = tokens_map_lock
        self._tokens_map = tokens_map
        self._state = state

    def _poll_calendar( self, calendar, credentials ):
        logging.info( "polling calendar %s", calendar["name"] )

        # TODO: precalculate this value
        calendars = list( map( lambda x: x["name"], self._config ) )

        refresh_credentials( calendar, credentials )

        update_valid_expired_metrics( calendar, credentials )

        result = []

        now = datetime.datetime.now()

        if credentials and credentials.valid:
            # TODO: only rebuild the service if the credentials change (a loop in a loop?)
            service = build( 'calendar', 'v3', credentials=credentials )
            now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time

            for c in service.calendarList().list().execute().get('items'):
                if c["summary"] not in calendars and ("primary" not in c or not c["primary"]):
                    logging.debug("skipping calendar %s", c["summary"])
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
                    local_now = datetime.datetime.now( datetime.timezone.utc ).astimezone()

                    start_time = event['start'].get( 'dateTime', event['start'].get( 'date' ) )[::-1].replace( ":", "", 1 )[::-1]
                    # All day events have a start time of YYYY-mm-dd
                    if ISO_DATE_PATTERN.match( start_time ) is None:
                        logging.debug("skipping %s", start_time)
                        continue

                    start_time = datetime.datetime.strptime(
                        start_time,
                        "%Y-%m-%dT%H:%M:%S%z" )

                    end_time = event['end'].get( 'dateTime', event['end'].get( 'date' ) )[::-1].replace( ":", "", 1 )[::-1]
                    end_time = datetime.datetime.strptime(
                        end_time,
                        "%Y-%m-%dT%H:%M:%S%z" )

                    if ( start_time - local_now ).total_seconds() < 0 and \
                    ( end_time - local_now ).total_seconds() > 0:
                        logging.info( "Current event: %s", event["summary"] )
                        result.append( event )

        return result


    def work( self ):
        calendar_name = self._calendar["name"]
        try:
            credentials = None
            with self._tokens_map_lock:
                credentials = self._tokens_map[calendar_name]
                old_state = self._state[calendar_name] if calendar_name in self._state else []

            new_state = self._poll_calendar( self._calendar, credentials )
            if new_state != old_state:
                if len( old_state ) == 0:
                    self._ws.enable( self._calendar["notification"] )

                elif len( new_state ) == 0:
                    self._ws.disable( self._calendar["notification"] )

            with self._tokens_map_lock:
                self._state[calendar_name] = new_state

        except Exception as e:
            logging.exception( e )
            workunitExceptions.labels( calendar_name ).inc( 1 )

        finally:
            future = datetime.datetime.now() + datetime.timedelta( seconds=60 )
            self._workqueue.enqueue(
                CalendarWorkunit(
                    self._config,
                    self._ws,
                    future,
                    self._calendar,
                    self._workqueue,
                    self._tokens_map_lock,
                    self._tokens_map,
                    self._state ) )


class CalendarListener( Sensor ):
    def __init__(self, args):
        super().__init__(args, "Calendar Listener", "/calendarListener")
        self._tokens_map = {}
        self._tokens_map_lock = threading.Lock()
        self._state = {}

    @override
    def _get_httpd_handler(self) -> http.server.BaseHTTPRequestHandler:
        def get_config():
            return self._config
        def get_tokens_map_lock():
            return self._tokens_map_lock
        def get_tokens_map():
            return self._tokens_map
        class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
            def do_GET( self ): # pylint: disable=invalid-name
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

                        calendar = list( filter( lambda c: c["name"] == query["state"][0], get_config() ) )[0]
                        refresh_credentials( calendar, token )

                        with get_tokens_map_lock():
                            get_tokens_map()[calendar["name"]] = token

                        status = 302
                        headers["Location"] = httpPathPrefix + "/"

                    elif self.path.startswith( httpPathPrefix + "/flow?" ):
                        calendar = self.path[len( httpPathPrefix + "/flow?" ):]

                        flow = InstalledAppFlow.from_client_secrets_file(
                                credentialsFile, SCOPES, redirect_uri="http://localhost:8080" + httpPathPrefix )
                        auth_url, _ = flow.authorization_url(
                                access_type="offline",
                                prompt='consent',
                                state=calendar )

                        status = 302
                        headers = { "Location": auth_url }

                    # TODO: better to do a refex match? (or normalize to either always include or always
                    # not have the trailing "/"?)
                    elif self.path.startswith( httpPathPrefix ):
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

                        with get_tokens_map_lock():
                            for key, token in get_tokens_map().items():
                                response += "<tr><td>" + key + "</td>" + \
                                            "<td>(" + ("not " if not token or not token.valid else "") + "valid)</td>" + \
                                            "<td><a href='" + httpPathPrefix + "/flow?" + key + "'>link</a></td>"
                                # TODO: report which calendar event is current, if any


                        # TODO: include configuration
                        response += """
                                        </tbody>
                                    </table>
                                    <h3>Configuration</h3>
                                    <pre class="bg-light">""" + \
                                    yaml.dump( get_config(),
                                               sort_keys=True,
                                               indent=2 ) + \
                                    """</pre>
                                </body>
                            </html>
                        """
                        status = 200

                finally:
                    self.send_response( status )
                    for key, value in headers.items():
                        self.send_header( key, value )
                    self.end_headers()
                    if response is not None:
                        if isinstance( response, str ):
                            response = response.encode( "utf-8" )
                        self.wfile.write( response )
        return HTTPRequestHandler

    @override
    def main(self) -> int:
        result = super().main()
        if result != 0:
            return result
        if self._config is not None:
            for calendar in self._config:
                try:
                    workunitExceptions.labels( calendar["name"] ).set( 0 )

                    self._tokens_map[calendar["name"]] = None
                    self._state[calendar["name"]] = []

                    # TODO: only enqueue for linked accounts
                    self._workqueue.enqueue(
                        CalendarWorkunit(
                            self._config,
                            self._ws,
                            datetime.datetime.now(),
                            calendar,
                            self._workqueue,
                            self._tokens_map_lock,
                            self._tokens_map,
                            self._state ) )

                    f = get_token_filename( calendar )
                    if os.path.exists( f ):
                        credentials = Credentials.from_authorized_user_file( f, SCOPES )
                        if credentials:
                            # Need to refresh the token because credentials.valid initializes to False
                            refresh_credentials( calendar, credentials )
                        self._tokens_map[calendar["name"]] = credentials
                        update_valid_expired_metrics( calendar, credentials )

                except Exception as e:
                    # Catch the exception and continue. Hopefully, we'll be able to proceed on other calendars.
                    logging.exception( e )

            # The file token.json stores the user's access and refresh tokens, and is
            # created automatically when the authorization flow completes for the first
            # time.

        self._up.set(1)
        self._terminate_semaphore.acquire()

        # TODO: if the websocket never connects, it won't stop
        # TODO: file issue
        #self._ws.stop()
        self._workqueue.stop()

        return 0


if __name__ == '__main__':
    sys.exit( CalendarListener( sys.argv ).main() )
