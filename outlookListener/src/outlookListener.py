import argparse
import atexit
import datetime
import http
import http.server
import json
import logging
import os
import sys
import threading
import urllib
import urllib.parse
import uuid
from typing import override

import msal
import requests
import yaml

from prometheus_client import Gauge

from myblinkstick.application import Sensor
from myblinkstick.navbar import Navbar
from myblinkstick.workqueue import Workunit


credentialsInvalid = Gauge(
        'credentialsInvalid',
        'Indicates whether or not the credentials are invalid',
        ['calendar'] )
credentialsExpired = Gauge(
        'credentialsExpired',
        'Indicates whether or not the credentials are expired',
        ['calendar'] )
workunitExceptions = Gauge(
        'workunitExceptions',
        'The number of exceptions caused by work units for a particular calendar',
        ['calendar', 'exceptionName'] )

class OutlookWorkunit( Workunit ):
    def __init__( self,
                  ws,
                  dt,
                  calendar,
                  workqueue,
                  state_lock,
                  state,
                  tokens_cache,
                  app,
                  credentials ):
        super().__init__( dt )
        self._ws = ws
        self._calendar = calendar
        self._workqueue = workqueue
        self._state_lock = state_lock
        self._state = state
        self._tokens_cache = tokens_cache
        self._app = app
        self._credentials = credentials

    def poll_calendar( self, calendar ):
        result = []

        if self._tokens_cache is not None:
            account = self._app.get_accounts( calendar["name"] )

            # TODO:  is there a better way to check if the credentials are valid?
            credentialsInvalid.labels( calendar["name"] ).set( 1 if account is None or len( account ) == 0 else 0 )

        else:
            raise Exception()

        if account is not None and len(account) != 0:
            if len(account) > 1:
                logging.warning( "More than 1 authorization token for %s", calendar )

            authorization_token = None

            acquire_result = self._app.acquire_token_silent_with_error(self._credentials["scope"], account[0], force_refresh=True)
            # TODO: could I listen to the msal.token_cache event, and look for an
            # `expires_in` < 1000 (or `ext_expires_in` < 1000?)

            # TODO: The expires_in value seems to float around. I would expect that
            # the force_refresh would lock it to some externally specified maximum
            if "error" in acquire_result:
                raise Exception(acquire_result["error"])

            authorization_token = acquire_result["access_token"]

            now = datetime.datetime.utcnow()
            enddate = now + datetime.timedelta( 0,
                                                60 * 60 * 24 ) # 1 day
            url = "https://graph.microsoft.com/v1.0/me/calendarview?startdatetime=%(start)s&enddatetime=%(end)s" % \
                    { "start": now.strftime("%Y-%m-%dT%H:%M:%S.") + '000Z',
                    "end": enddate.strftime("%Y-%m-%dT%H:%M:%S.") + '000Z' }
            headers = {
                    'Authorization': authorization_token
            }

            events_result = requests.get( url=url, headers=headers, timeout=10 )

            o = json.loads( events_result.text )
            local_now = datetime.datetime.now()
            if "value" in o:
                if len( o["value"] ) > 0:
                    start_time = o["value"][0]["start"]["dateTime"][:-1]
                    end_time = o["value"][0]["end"]["dateTime"][:-1]

                    start_time = datetime.datetime.strptime(
                        start_time,
                        "%Y-%m-%dT%H:%M:%S.%f" )
                    end_time = datetime.datetime.strptime(
                        end_time,
                        "%Y-%m-%dT%H:%M:%S.%f" )

                    if start_time <= local_now <= end_time:
                        result.append( o["value"][0] )
            else:
                raise Exception( o )

        return result

    @override
    def work( self ):
        calendar_name = self._calendar["name"]
        try:
            old_state = None
            with self._state_lock:
                old_state = self._state[calendar_name] if calendar_name in self._state else []

            new_state = self.poll_calendar( self._calendar )
            if new_state != old_state:
                if len( old_state ) == 0:
                    self._ws.enable( self._calendar["notification"] )

                elif len( new_state ) == 0:
                    self._ws.disable( self._calendar["notification"] )

            with self._state_lock:
                self._state[calendar_name] = new_state

        except Exception as e:
            logging.exception( e )
            workunitExceptions.labels( calendar_name, type( e ).__name__ ).inc( 1 )

        finally:
            future = datetime.datetime.now() + datetime.timedelta( seconds=60 )
            self._workqueue.enqueue(
                OutlookWorkunit(
                    self._ws,
                    future,
                    self._calendar,
                    self._workqueue,
                    self._state_lock,
                    self._state,
                    self._tokens_cache,
                    self._app,
                    self._credentials ) )


class OutlookListener( Sensor ):
    def __init__(self, args):
        super().__init__(args, "Outlook Listener", "/outlookListener")
        self._state_lock = threading.Lock()
        self._state = {}
        self._app = None
        self._tokens_cache = None
        self._credentials = None
        self._tokens_file = None

    @override
    def _get_httpd_handler(self):
        http_path_prefix = self._http_path_prefix
        config = self._config
        def get_app():
            return self._app
        def get_credentials():
            return self._credentials
        save_tokens_cache = self.save_tokens_cache
        def get_tokens_cache():
            return self._tokens_cache

        class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
            def do_GET( self ): # pylint: disable=invalid-name
                response = None
                status = 500
                headers = {}

                try:
                    parse = urllib.parse.urlparse( self.path )
                    query = urllib.parse.parse_qs( parse.query )

                    if "code" in query and \
                    "session_state" in query:
                        credentials = get_credentials()
                        assert credentials is not None

                        app = get_app()
                        assert app is not None

                        code = query["code"][0]
                        app.acquire_token_by_authorization_code(
                            code,
                            scopes=credentials["scope"],
                            redirect_uri=credentials["redirect_uri"] )
                        status = 307
                        headers["Location"] = "/" if http_path_prefix == "" else http_path_prefix
                        save_tokens_cache()

                    elif self.path.startswith( http_path_prefix + "/flow?" ):
                        credentials = get_credentials()
                        assert credentials is not None

                        app = get_app()
                        assert app is not None

                        auth_state = str(uuid.uuid4())
                        authorization_url = app.get_authorization_request_url(
                            credentials['scope'],
                            state=auth_state,
                            redirect_uri=credentials['redirect_uri'] )
                        save_tokens_cache()
                        status = 307
                        headers = {"Location": authorization_url}

                    elif self.path.startswith( http_path_prefix ):
                        response = """
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

                        for calendar in config:
                            valid = False
                            if get_tokens_cache() is not None:
                                app = get_app()
                                if app is not None:
                                    authorization_token = app.get_accounts( calendar["name"] )
                            if authorization_token is not None and len(authorization_token) != 0:
                                valid = True

                            response += "<tr><td>" + calendar["name"] + "</td>"
                            # TODO: there may be more to check: this reports valid even
                            # though get_accounts() is returning an empty list.
                            response += "<td>(" + ("not " if not valid else "") + "valid)</td>"
                            response += "<td><a href='" + http_path_prefix + "/flow?" + calendar["name"] + "'>link</a></td>"
                            # TODO: report which calendar event is current, if any


                        response += """
                                        </tbody>
                                    </table>
                                    <h3>Configuration</h3>
                                    <pre class="bg-light">"""
                        response += yaml.dump( config,
                                               sort_keys=True,
                                               indent=2 )
                        response += """</pre>
                                </body>
                            </html>
                        """
                        status = 200

                    elif self.path == "/" and http_path_prefix != "/":
                        status = 307
                        headers["Location"] = http_path_prefix

                    elif self.path == "/health":
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
    def get_arg_parser( self ) -> argparse.ArgumentParser:
        parser = super().get_arg_parser()
        parser.add_argument('--tokens-file',
                            help='Path to tokens file',
                            default='/tokens/cache.bin',
                            dest='tokens_file')
        parser.add_argument('--credentials-file',
                            help='Path to credentials.yaml file',
                            default='credentials.yaml',
                            dest='credentials_file')
        return parser

    def save_tokens_cache(self):
        if self._tokens_file is not None and \
           self._tokens_cache is not None and \
           self._tokens_cache.has_state_changed:
            with open( self._tokens_file, encoding="ascii" ) as f:
                f.write( self._tokens_cache.serialize() )

    def main(self):
        result: int = super().main()
        if result != 0:
            return result

        with open(self._parsed_args.credentials_file, encoding='ascii') as f:
            self._credentials = yaml.safe_load( f )

        self._tokens_file = self._parsed_args.tokens_file
        self._tokens_cache = msal.SerializableTokenCache()
        if os.path.exists( self._tokens_file ):
            self._tokens_cache.deserialize( open( self._tokens_file, "r", encoding="ascii" ).read() )
        atexit.register( self.save_tokens_cache )

        self._app = msal.ConfidentialClientApplication(
                client_id=self._credentials["client_id"],
                authority=self._credentials["authority"],
                client_credential=self._credentials["client_secret"])

        assert self._workqueue is not None
        for calendar in self._config:
            workunitExceptions.labels( calendar["name"], 'Exception' ).set( 0 )

            self._state[calendar["name"]] = []

            self._workqueue.enqueue(
                OutlookWorkunit(
                    self._ws,
                    datetime.datetime.now(),
                    calendar,
                    self._workqueue,
                    self._state_lock,
                    self._state,
                    self._tokens_cache,
                    self._app,
                    self._credentials ) )

        self._up.set(1)

        assert self._terminate_semaphore is not None
        self._terminate_semaphore.acquire()

        return 0

if __name__ == "__main__":
    sys.exit( OutlookListener(sys.argv).main() )
