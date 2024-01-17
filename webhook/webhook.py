import http
import json
import logging
import os
import sys
import threading
import urllib
import websocket
import yaml

from navbar import Navbar
from websocketClient import WebsocketClient

from prometheus_client import start_http_server, Gauge
from prometheus_client.core import REGISTRY

logging.basicConfig( level=logging.DEBUG )

up =    Gauge(
        'up',
        'Whether or not the ledController is running' )
up.set( 0 )

testAlert = Gauge(
        'testAlert',
        'Used to test enabling and disabling alerts')
testAlert.set( 0 )

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

config = None
oldState = None
ws = None

def getBlinkstickAlertForPrometheusAlert( alert ):
    global config

    if config is not None and "map" in config \
   and alert["labels"]["alertname"] in config["map"]:
        for condition in config["map"][alert["labels"]["alertname"]]:
            label = condition["label"]
            if label in alert["labels"] and alert["labels"][label] == condition["value"]:
                return condition["alert"]

    return config["defaultEvent"]

class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
    alerts = {}

    # TODO: do I need to watch for an alertmanager restart to clear alerts? I
    # think we can periodically check the alertmanager_cluster_peer_info{peer=""}
    # to see if we've lost an alert manager
    def do_GET( self ):
        global config

        response = None
        status = 500
        headers = {}
        try:
            if self.path == httpPathPrefix + "/testAlert/set" or \
               self.path == httpPathPrefix + "/testAlert/unset":
                testAlert.set( 1 if testAlert._value.get() == 0 else 0 )
                status = 307
                headers["Location"] = httpPathPrefix + "/"

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

                            <style>
                                pre {
                                  border-radius: 10px;
                                  font-family: Consolas,monospace;
                                  margin-bottom: 10px;
                                  overflow: auto;
                                  padding: 10px;
                                }
                            </style>
                        </head>
                        <body>
                        """ \
                    + Navbar().render() \
                    + """
                            <a href="%(url)s">%(link)s</a>
                    """ % {"url":  httpPathPrefix + "/testAlert/" + ("set" if testAlert._value.get() == 0 else "unset"),
                           "link":                                  ("set" if testAlert._value.get() == 0 else "unset")} \
                    + "<h3>Current Alerts</h3><pre>" \
                    + str( self.alerts ) \
                    + """
                        </pre>
                        <h3>Configuration</h3>
                        <pre class="bg-light">""" \
                    + yaml.dump( config,
                                 sort_keys=True,
                                 indent=2 ) \
                    + """</pre>
                        </body>
                    </html>
                    """
                status = 200

            elif self.path == "/health":
                status = 200

        finally:
            self.send_response( status )
            if response is None:
                response = ""
            if type( response ) is str:
                response = response.encode( "utf-8" )
            if "Content-Length" not in headers:
                headers["Content-Length"] = len( response )
            for key in headers:
                self.send_header( key, headers[key] )
                self.end_headers()
            self.wfile.write( response )


    def do_POST( self ):
        global config
        global oldState
        global ws

        response = None
        status = 500
        headers = {}

        try:
            # Send the sample event notification with:
            #   cat sampleSetMessage.json | docker exec --interactive blinkstick_calendarListener_1 curl -X POST http://webhook:8080
            status = 200

            contentLength = int( self.headers.get( 'Content-Length' ) or 0 )
            event = json.loads( self.rfile.read( contentLength ) )
            logging.info( json.dumps( event, indent=4 ) )

            # TODO: Can the same alert be fired twice?
            #       It's possible to configure how many events are in each message, which
            #       might inform the answer
            for alert in event["alerts"]:
                blinkstickAlert = getBlinkstickAlertForPrometheusAlert( alert )
                logging.info( "blinkstickAlert: " + str( blinkstickAlert ) )

                if alert["status"] == "firing":
                    needToSend = False
                    if blinkstickAlert in self.alerts:
                        self.alerts[blinkstickAlert].add( alert["labels"]["alertname"] )
                    else:
                        needToSend = True
                        self.alerts[blinkstickAlert] = set( (alert["labels"]["alertname"],) )
                        if ws is not None:
                            ws.enable( blinkstickAlert )

                elif alert["status"] == "resolved":
                    if blinkstickAlert in self.alerts:
                        self.alerts[blinkstickAlert].remove( alert["labels"]["alertname"] )
                        if len( self.alerts[blinkstickAlert] ) == 0:
                            del self.alerts[blinkstickAlert]
                            if ws is not None:
                                ws.disable( blinkstickAlert )

            # TODO: there could be concurrency issues, I think
            if oldState != (len( self.alerts ) > 0):
                oldState = len( self.alerts ) > 0


        except Exception as e:
            logging.exception( e )

        finally:
            self.send_response( status )
            if response is None:
                response = ""
            if type( response ) is str:
                response = response.encode( "utf-8" )
            if "Content-Length" not in headers:
                headers["Content-Length"] = len( response )
            for key in headers:
                self.send_header( key, headers[key] )
                self.end_headers()
            self.wfile.write( response )


configFile =      os.environ["CONFIG_FILE"]      if "CONFIG_FILE"      in os.environ else "config.yml"
httpPathPrefix  = os.environ["HTTP_PATH_PREFIX"] if "HTTP_PATH_PREFIX" in os.environ else "/webhook"

if os.path.exists( configFile ):
    with open( configFile, 'r' ) as f:
        config = yaml.safe_load( f )
else:
    logging.warning( "Warning: using an empty config file" )
    config = []


def main( args ):
    global ws

    try:
        def httpdService():
            httpd = http.server.HTTPServer( ('', 8080), HTTPRequestHandler )
            httpd.serve_forever()
        httpd = threading.Thread( target=httpdService, daemon=True )
        httpd.start()

        start_http_server( 9000 )

        ws = WebsocketClient( "ws://led-controller:9099",
                              name="Webhook",
                              httpPathPrefix=httpPathPrefix )
        ws.start()

        up.set( 1 )

    except Exception as e:
        logging.exception( e )

    while True:
        import time
        time.sleep(10)

if __name__ == '__main__':
    sys.exit( main( sys.argv ) )


