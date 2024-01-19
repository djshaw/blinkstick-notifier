import http
import json
import jsonschema
import logging
import os
import signal
import socket
import sys
import threading
import yaml

from heap import HeapBy
from blinkstickThread import BlinkstickThread, BlinkstickDTO
from navbar import Navbar

from prometheus_client import start_http_server, Gauge
from prometheus_client.core import REGISTRY

from simple_websocket_server import WebSocketServer, WebSocket

# TODO: get logging level from environment variable
logging.basicConfig( level=logging.DEBUG )

clients = {}
clientsLock = threading.Lock()

up =    Gauge(
        'up',
        'Whether or not the ledController is running' )
up.set( 0 )

clientsGauge = Gauge(
        'clients',
        'Specifies which clients are connected',
        ['type'] )
clientTypes = set(['CalendarListener', 'OutlookListener', 'Webhook', 'Bitbucket', 'ManualSet', None])
for client in clientTypes:
    clientsGauge.labels( client ).set( 0 )

# TODO: report which clients have connected. Created an alert if the client's up doesn't match
# what the led controller reports


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


class Client( object ):
    name = None
    link = None


class WebSocketHandler( WebSocket ):
    def __init__( self, *args, **kwargs ):
        try:
            super().__init__( *args, *kwargs )
            self._blinkstickThread = blinkstickThread
            self._blinkstickClient = BlinkstickDTO( blinkstickThread, self.address )

            with open( "/app/receive.schema.json" ) as f:
                self._receiveSchema = json.load( f )

            with open( "/app/send.schema.json" ) as f:
                self._sendSchema = json.load( f )

        except Exception as e:
            logging.exception( e )
            raise e


    def _validateMessage( self, schema, message ):
        try:
            # TODO: add an environment variable or commandline parameter to
            # disable validation (in case it becomes a performance problem)
            jsonschema.validate( schema=schema, instance=message )
        except jsonschema.exceptions.ValidationError as e:
            logging.error( "Error validating json: %s", e )
        except jsonschema.exceptions.SchemaError as e:
            logging.error( "Error validating schema: %s", e )


    def send_message( self, message ):
        self._validateMessage( self._sendSchema, message )
        super().send_message( json.dumps( message ).encode( "ascii" ) )

    def _updateClientsGauges( self ):
        """ Populates the clients{type=$NAME} prometheus metrics """
        global clients

        # This function isn't very efficient. There are much better ways to implement. Performance
        # hasn't been a limitation yet.

        totalClientTypes = clientTypes \
                         | set( map( lambda x: clients[x].name, clients ) )
        for client in totalClientTypes:
            clientsGauge.labels( client if client is not None else "None" ) \
                        .set( len( list( filter( lambda x: clients[x].name == client, clients ) ) ) )

    def handle( self ):
        try:
            data = json.loads( self.data )
            self._validateMessage( self._receiveSchema, data )

            # {"ping": true} -> {"pong": true}
            if "ping" in data and data["ping"]:
                logging.debug( "Ping!" )
                self.send_message( {"pong": True} )
                return

            # {"enable": "type"} -> {"success": "true|false"}
            if "enable" in data:
                logging.debug( "socket thread enabling " + data["enable"] )
                self._blinkstickClient.enable( data["enable"] )
                self.send_message( {"success": True } )
                return

            # {"disable": "type"} -> {"success": "true|false"}
            if "disable" in data:
                logging.debug( "socket thread disabling " + data["disable"] )
                self._blinkstickClient.disable( data["disable"] )
                self.send_message( {"success": True } )
                return

            if "name" in data or "link" in data:
                with clientsLock:
                    if "name" in data:
                        clients[self.address].name = data["name"]

                    link = None
                    if "link" in data:
                        clients[self.address].link = data["link"]


                self._updateClientsGauges()


        except Exception as e:
            logging.exception( e )


    def connected( self ):
        global clients
        global clientsLock

        try:
            logging.debug( "adding client " + str( self.address ) )
            with clientsLock:
                clients[self.address] = Client()
                self._updateClientsGauges()
            self._blinkstickClient.register()

        except Exception as e:
            logging.exception( e )


    def handle_close( self ):
        global clients
        global clientsLock

        try:
            with clientsLock:
                logging.debug( "removing client " + str( self.address ) )
                if self.address in clients:
                    del clients[self.address]
                self._updateClientsGauges()
            self._blinkstickClient.unregister()

        except Exception as e:
            logging.exception( e )


    # TODO: if the thread terminates, remove it from the list of threads in main(), otherwise
    # we'll run out of memory
    # TODO: instead of recording a list of threads and connections, have a set of just active
    # connections?

class HTTPRequestHandler( http.server.BaseHTTPRequestHandler ):
    def do_GET( self ):
        global blinkstickThread
        global clients
        global config

        response = None
        status = 500
        headers = {}

        try:
            logging.info( 175 )
            currentAlerts = blinkstickThread.getCurrentAlerts()
            visibleAlerts = blinkstickThread.getVisibleAlerts()
            # TODO: add a websocket for pushing state updates to the web client
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
                    <h3>Current Alert</h3>
                       """ \
                + str( visibleAlerts ) \
                + """
                        <br>
                        <br>
                        <h3>Alerts Fired</h3>
                        <pre class="bg-light">""" \
                + str( currentAlerts ) \
                + """</pre>
                        <h3>Clients</h3>
                        <table class="table"><tr><th>Name</th><th>id</th></tr>"""

            with clientsLock:
                for id in clients:
                    client = clients[id]

                    name = None
                    if client.name is not None and client.name != "":
                        name = client.name
                    else:
                        name = str( id )

                    link = None
                    if client.link is not None and client.link != "":
                        link = "<a href=\"" + client.link + "\">" + client.name + "</a>"
                    else:
                        link = name

                    if link == None:
                        link = ""

                    response += "<tr><td>" + link + "</td><td>" + str( id ) + "<td></tr>"

            response += """
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
            logging.info( 250 )

        except Exception as e:
            logging.exception( e )

        finally:
            self.send_response( status )
            for key in headers:
                self.send_header( key, headers[key] )
            self.end_headers()
            if response != None:
                if type( response ) is str:
                    response = response.encode( "utf-8" )
                self.wfile.write( response )


def httpdService():
    # TODO: make port configurable
    httpd = http.server.HTTPServer( ('', 8080), HTTPRequestHandler )
    httpd.serve_forever()


terminateSemaphore = threading.Semaphore(0)
def signalHandler( signum, frame ):
    if signum == signal.SIGINT or signum == signal.SIGTERM:
        terminateSemaphore.release()

        # TODO: doesn't actually work: perhaps because of a subprocess started
        # by blinkstick, or because of a thread
        sys.exit( 0 )

configFile =      os.environ["CONFIG_FILE"]      if "CONFIG_FILE"      in os.environ else "/app/config.yml"

blinkstickThread = None

def main( argv ):
    global config
    global alertPrioritiesMap
    global blinkstickThread

    signal.signal( signal.SIGINT,  signalHandler )
    signal.signal( signal.SIGTERM, signalHandler )

    if os.path.exists( configFile ):
        with open( configFile, 'r' ) as f:
            config = yaml.safe_load( f )
        # TODO: validate config?
    else:
        logging.warning( "Warning: using an empty config file" )
        config = []

    start_http_server( 9000 )

    httpd = threading.Thread( target=httpdService, daemon=True )
    httpd.start()

    blinkstickThread = BlinkstickThread( config )
    blinkstickThread.start()

    def custom_hook( args ):
        logging.exception( args )
    threading.excepthook = custom_hook


    def startWebsocketServer():
        try:
            logging.info("starting websocket handler...")
            server = WebSocketServer( '0.0.0.0', 9099, WebSocketHandler )
            server.serve_forever()
        except Exception as e:
            logging.exception( e )
    websocketThread = threading.Thread( target=startWebsocketServer, daemon=True )
    websocketThread.start()


    up.set( 1 )

    terminateSemaphore.acquire()

    blinkstick.terminate()

    manager.join()
    controllerThread.join()

    return 0


if __name__ == "__main__":
    # TODO: print a log at start up so the docker logs have a delimiter between
    # launches
    sys.exit( main( sys.argv ) )

