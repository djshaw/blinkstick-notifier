import atexit
import datetime
import http
import json
import logging
import msal
import os
import requests
import sys
import threading
import time
import traceback
import urllib
import uuid
import websocket
import yaml

from workunit import WorkQueue, Workunit, installWorkunitsCollector
from navbar import Navbar

from websocketClient import WebsocketClient

from simple_websocket_server import WebSocketServer, WebSocket

from prometheus_client import start_http_server, Gauge
from prometheus_client.core import REGISTRY

logging.basicConfig( level=logging.DEBUG )
# Remove the default logger. It allows log messages to contain a new line
logging.getLogger('').handlers = []

class LogFormatter( logging.Formatter ):
    def __init__( self, fmt=None, datefmt=None ):
        super( self.__class__, self ).__init__( fmt=fmt, datefmt=datefmt )
        self.stringFormatter = logging.Formatter( "%(levelname)s:%(name)s:%(message)s" )

    def format( self, record ):
        return self.stringFormatter.format( record ).replace( "\n", "\\n" )
handler = logging.StreamHandler()
handler.setFormatter( LogFormatter() )
logging.getLogger('').addHandler( handler )


credentialsFile = os.environ["CREDENTIALS_FILE"] if "CREDENTIALS_FILE" in os.environ else "credentials.yaml"
credentials = yaml.safe_load( open( credentialsFile ) )

SCOPES = credentials["scope"]

configFile =      os.environ["CONFIG_FILE"]      if "CONFIG_FILE"      in os.environ else "/config.ymal"

up =    Gauge(
        'up',
        'Whether or not the calendarListener is running' )
up.set( 0 )


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

tokensFile =      os.environ["TOKENS_FILE"]      if "TOKENS_FILE"      in os.environ else "/tokens/cache.bin"

tokensCache = msal.SerializableTokenCache()
if os.path.exists( tokensFile ):
    tokensCache.deserialize( open( tokensFile, "r" ).read() )
def saveTokensCache():
    if tokensCache.has_state_changed:
        open( tokensFile, "w" ).write( tokensCache.serialize() )
atexit.register( lambda: saveTokensCache() )

app = msal.ConfidentialClientApplication(
        client_id=credentials["client_id"],
        authority=credentials["authority"],
        client_credential=credentials["client_secret"],
        token_cache=tokensCache )


class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
    def do_GET( self ):
        global config
        response = None
        status = 500
        headers = {}

        try:
            parse = urllib.parse.urlparse( self.path )
            query = urllib.parse.parse_qs( parse.query )

            if "code" in query and \
               "session_state" in query:
                code = query["code"][0]
                token = app.acquire_token_by_authorization_code( code, scopes=credentials["scope"], redirect_uri=credentials["redirect_uri"] )
                status = 307
                headers["Location"] = "/" if httpPathPrefix == "" else httpPathPrefix
                saveTokensCache()

            elif self.path.startswith( httpPathPrefix + "/flow?" ):
                auth_state = str(uuid.uuid4())
                authorization_url = app.get_authorization_request_url( credentials['scope'],
                                                                       state=auth_state,
                                                                       redirect_uri=credentials['redirect_uri'] )
                saveTokensCache()
                status = 307
                headers = {"Location": authorization_url}

            elif self.path.startswith( httpPathPrefix ):
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
                    if tokensCache is not None:
                        authorizationToken = app.get_accounts( calendar["name"] )
                    if authorizationToken is not None and len(authorizationToken) != 0:
                        valid = True

                    response += "<tr><td>" + calendar["name"] + "</td>"
                    # TODO: there may be more to check: this reports valid even
                    # though get_accounts() is returning an empty list.
                    response += "<td>(" + ("not " if not valid else "") + "valid)</td>"
                    response += "<td><a href='" + httpPathPrefix + "/flow?" + calendar["name"] + "'>link</a></td>"
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

            elif self.path == "/" and httpPathPrefix != "/":
                status = 307
                headers["Location"] = httpPathPrefix

            elif self.path == "/health":
                status = 200


        finally:
            self.send_response( status )
            for key in headers:
                self.send_header( key, headers[key] )
            self.end_headers()
            if response != None:
                if type( response ) is str:
                    response = response.encode( "utf-8" )
                self.wfile.write( response )


class OutlookWorkunit( Workunit ):
    def __init__( self, ws, dt, calendar ):
        self._ws = ws
        self._calendar = calendar
        super().__init__( dt )

    def work( self ):
        global lock
        global state
        global workqueue

        calendarName = self._calendar["name"]
        try:
            with lock:
                oldState = state[calendarName] if calendarName in state else []

            newState = pollCalendar( self._calendar )
            if newState != oldState:
                if len( oldState ) == 0:
                    self._ws.enable( self._calendar["notification"] )

                elif len( newState ) == 0:
                    self._ws.disable( self._calendar["notification"] )

            with lock:
                state[calendarName] = newState

        except Exception as e:
            logging.exception( e )
            workunitExceptions.labels( calendarName, type( exception ).__name__ ).inc( 1 )

        finally:
            future = datetime.datetime.now() + datetime.timedelta( seconds=60 )
            workqueue.enqueue( OutlookWorkunit( self._ws, future, self._calendar ) )



def pollCalendar( calendar ):
    result = []

    if tokensCache is not None:
        account = app.get_accounts( calendar["name"] )

        # TODO:  is there a better way to check if the credentials are valid?
        credentialsInvalid.labels( calendar["name"] ).set( 1 if account is None or len( account ) == 0 else 0 )

    else:
        raise Exception()

    if account is not None and len(account) != 0:
        if len(account) > 1:
            logging.warning( "More than 1 authorization token for " + calendar )

        authorizationToken = None

        acquireResult = app.acquire_token_silent_with_error(credentials["scope"], account[0], force_refresh=True)
        # TODO: could I listen to the msal.token_cache event, and look for an
        # `expires_in` < 1000 (or `ext_expires_in` < 1000?)

        # TODO: The expires_in value seems to float around. I would expect that
        # the force_refresh would lock it to some externally specified maximum
        if "error" in acquireResult:
            raise Exception(acquireResult["error"])
        else:
            authorizationToken = acquireResult["access_token"]
        
        now = datetime.datetime.utcnow()
        enddate = now + datetime.timedelta( 0,
                                            60 * 60 * 24 ) # 1 day
        url = "https://graph.microsoft.com/v1.0/me/calendarview?startdatetime=%(start)s&enddatetime=%(end)s" % \
                { "start": now.strftime("%Y-%m-%dT%H:%M:%S.") + '000Z',
                  "end": enddate.strftime("%Y-%m-%dT%H:%M:%S.") + '000Z' }
        headers = {
                'Authorization': authorizationToken
        }

        events_result = requests.get( url=url, headers=headers )

        o = json.loads( events_result.text )
        localNow = datetime.datetime.now()
        if "value" in o:
            if len( o["value"] ) > 0:
                startTime = o["value"][0]["start"]["dateTime"][:-1]
                endTime = o["value"][0]["end"]["dateTime"][:-1]

                startTime = datetime.datetime.strptime(
                    startTime,
                    "%Y-%m-%dT%H:%M:%S.%f" )
                endTime = datetime.datetime.strptime(
                    endTime,
                    "%Y-%m-%dT%H:%M:%S.%f" )

                if startTime <= localNow and localNow <= endTime:
                    result.append( o["value"][0] )
        else:
            raise Exception( o )

    return result

configFile =      os.environ["CONFIG_FILE"]      if "CONFIG_FILE"      in os.environ else "config.yml"
httpPathPrefix  = os.environ["HTTP_PATH_PREFIX"] if "HTTP_PATH_PREFIX" in os.environ else "/outlookListener"


sem = threading.Semaphore( 0 )
def on_open( ws ):
    ws.send( json.dumps( { "name": "OutlookListener",
                           "link": httpPathPrefix } ).encode( "ascii" ) )
    sem.release()


def on_message( ws, message ):
    # This websocket will only receive responses. We can ignore them for the most part
    logging.debug( "on_message: " + str( message ) )

def on_error( ws, error ):
    logging.error( "on_error(): " + str( error ) )

def on_close( ws, closeCode, closeMessage ):
    logging.debug( "on_close" )


# An experiement to see if it would be useful to write logs to a websocket. The
# logs would be printed to the html diagnostic page. An alternative to
# investigate is the grafana log manager.
class WebSocketHandler( WebSocket ):
    def handle( self ):
        logging.info("WebSocketHandler::handle()")

    def write( self, message ):
        try:
            self.send_message( message )
        except Exception as e:
            logging.exception( e )

    def connected( self ):
        try:
            logging.info("WebSocketHandler::connected()")

            logger = logging.getLogger()
            self.streamHandler = logging.StreamHandler( self )
            logger.addHandler( self.streamHandler )
        except Exception as e:
            logging.exception( e )

    def handle_close( self ):
        try:
            logging.info("WebSocketHandler::handle_close()")

            logger = logging.getLogger()
            logger.removeHandler( self.streamHandler )
        except Exception as e:
            logging.exception( e )


lock = threading.Lock()
workqueue = None
state = {}

def main( argv ):
    global workqueue
    global config
    global ws

    config = None
    if os.path.exists( configFile ):
        with open( configFile, 'r' ) as f:
            config = yaml.safe_load( f )

    else:
        logging.warning( "Warning: using an empty config" )
        config = []

    start_http_server( 9000 )

    def startWebsocketServer():
        try:
            server = WebSocketServer('0.0.0.0', 1011, WebSocketHandler )
            server.serve_forever()
        except Exception as e:
            logging.exception( e )
    websocketThread = threading.Thread( target=startWebsocketServer )
    websocketThread.start()


    ws = WebsocketClient( "ws://led-controller:9099",
                          name="OutlookListener",
                          httpPathPrefix="/outlookListener" )
    ws.start()


    # start the credentails web service thing
    def httpdService():
        httpd = http.server.HTTPServer( ('', 8080), HTTPRequestHandler )
        httpd.serve_forever()

    httpd = threading.Thread( target=httpdService )
    httpd.start()


    workqueue = WorkQueue()
    installWorkunitsCollector( workqueue )

    for calendar in config:
        workunitExceptions.labels( calendar["name"], 'Exception' ).set( 0 )

        state[calendar["name"]] = []

        workqueue.enqueue( OutlookWorkunit( ws, datetime.datetime.now(), calendar ) )

    workqueue.start()
    up.set( 1 )

    # TODO: don't busy wait. Use a semaphore. If we finish the main thread, we're
    # not allowed to allocate new ones
    while True:
        import time
        time.sleep(10)



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


if __name__ == "__main__":
    sys.exit( main( sys.argv ) )


