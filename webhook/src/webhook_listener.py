import http
from http.server import BaseHTTPRequestHandler
import json
import logging
import sys
import yaml

from myblinkstick.navbar import Navbar
from myblinkstick.application import Sensor

from prometheus_client import Gauge

logging.basicConfig( level=logging.DEBUG )

test_alert = Gauge(
        'testAlert',
        'Used to test enabling and disabling alerts')
test_alert.set( 0 )

def get_blinkstick_alert_for_prometheus_alert(config, alert ):
    if config is not None and "map" in config \
   and alert["labels"]["alertname"] in config["map"]:
        for condition in config["map"][alert["labels"]["alertname"]]:
            label = condition["label"]
            if label in alert["labels"] and alert["labels"][label] == condition["value"]:
                return condition["alert"]

    if "defaultEvent" in config:
        return config["defaultEvent"]
    return None


class HttpdWsCourier:
    ws = None


class WebhookListener( Sensor ):
    def __init__(self, args):
        super().__init__(args, "Webhook Listener", "/webhook")
        self._alerts = {}
        self._ws_courier = HttpdWsCourier()

    def _get_httpd_handler(self) -> BaseHTTPRequestHandler:
        alerts = self._alerts
        http_path_prefix = self._http_path_prefix
        config = self._config
        ws_courier = self._ws_courier

        class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
            # TODO: do I need to watch for an alertmanager restart to clear alerts? I
            # think we can periodically check the alertmanager_cluster_peer_info{peer=""}
            # to see if we've lost an alert manager
            def do_GET( self ): # pylint: disable=invalid-name
                response = None
                status = 500
                headers = {}
                try:
                    if self.path == http_path_prefix + "/testAlert/set" or \
                    self.path == http_path_prefix + "/testAlert/unset":
                        test_alert.set( 1 if test_alert._value.get() == 0 else 0 ) # pylint: disable=protected-access
                        status = 307
                        headers["Location"] = http_path_prefix + "/"

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
                            """ % {"url":  http_path_prefix + "/testAlert/" + ("set" if test_alert._value.get() == 0 else "unset"),
                                   "link":                                    ("set" if test_alert._value.get() == 0 else "unset")} \
                            + "<h3>Current Alerts</h3><pre>" \
                            + str( alerts ) \
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
                    if isinstance( response, str ):
                        response = response.encode( "utf-8" )
                    if "Content-Length" not in headers:
                        headers["Content-Length"] = len( response )
                    for key, value in headers.items():
                        self.send_header( key, value )
                        self.end_headers()
                    self.wfile.write( response )


            def do_POST( self ): # pylint: disable=invalid-name
                response = None
                status = 500
                headers = {}

                try:
                    status = 200

                    content_length = int( self.headers.get( 'Content-Length' ) or 0 )
                    event = json.loads( self.rfile.read( content_length ) )
                    logging.info( json.dumps( event, indent=4 ) )

                    # TODO: Can the same alert be fired twice?
                    #       It's possible to configure how many events are in each message, which
                    #       might inform the answer
                    for alert in event["alerts"]:
                        blinkstick_alert = get_blinkstick_alert_for_prometheus_alert( config, alert )

                        if alert["status"] == "firing":
                            if blinkstick_alert in alerts:
                                alerts[blinkstick_alert].add( alert["labels"]["alertname"] )
                            else:
                                alerts[blinkstick_alert] = set( (alert["labels"]["alertname"],) )
                                if ws_courier.ws is not None:
                                    ws_courier.ws.enable( blinkstick_alert )
                                else:
                                    logging.error("wsCourier.ws is None!")

                        elif alert["status"] == "resolved":
                            if blinkstick_alert in alerts:
                                alerts[blinkstick_alert].remove( alert["labels"]["alertname"] )
                                if len( alerts[blinkstick_alert] ) == 0:
                                    del alerts[blinkstick_alert]
                                    if ws_courier.ws is not None:
                                        ws_courier.ws.disable( blinkstick_alert )
                                    else:
                                        logging.error("wsCourier.ws is None!")

                except Exception as e:
                    logging.exception( e )

                finally:
                    self.send_response( status )
                    if response is None:
                        response = ""
                    if isinstance( response, str ):
                        response = response.encode( "utf-8" )
                    if "Content-Length" not in headers:
                        headers["Content-Length"] = len( response )
                    for key, value in headers.items():
                        self.send_header( key, value )
                    self.end_headers()
                    self.wfile.write( response )
        return HTTPRequestHandler

    def main(self):
        result = super().main()
        if result != 0:
            return result
        # The httpd server is started before the websocket, but the httpd server needs the
        # websocket to send enabled messages to the controller.  Use a courier to backfil the
        # websocket client connection.
        self._ws_courier.ws = self._ws
        self._up.set(1)
        self._terminate_semaphore.acquire()

        return 0

if __name__ == '__main__':
    sys.exit( WebhookListener( sys.argv ).main() )
