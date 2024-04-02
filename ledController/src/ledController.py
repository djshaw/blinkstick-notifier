import argparse
import http
import http.server
import json
import logging
import os
import sys
import threading
from functools import partial
from typing import override

import yaml
import jsonschema
import jsonschema.exceptions

from blinkstickThread import BlinkstickThread, BlinkstickDTO
from myblinkstick.navbar import Navbar
from myblinkstick.application import Application

from prometheus_client import Gauge

from simple_websocket_server import WebSocketServer, WebSocket

clients_gauge = Gauge(
        'clients',
        'Specifies which clients are connected',
        ['type'] )
CLIENT_TYPES = set(['Calendar Listener',
                    'Outlook Listener',
                    'Webhook Listener',
                    'Bitbucket Listener',
                    'ManualSet',
                    None])
for client in CLIENT_TYPES:
    clients_gauge.labels( client ).set( 0 )


class Client:
    name = None
    link = None


class WebSocketHandler( WebSocket ):
    def __init__( self,
                  receive_schema:    object | None,
                  send_schema:       object | None,
                  blinkstick_thread: BlinkstickThread,
                  address:           str,
                  clients_lock:      threading.Lock,
                  clients:           dict,
                  *args,
                  **kwargs ):
        try:
            self._blinkstick_thread = blinkstick_thread
            self._clients = clients
            self._clients_lock = clients_lock
            self._receive_schema = receive_schema
            self._send_schema = send_schema

            super().__init__( *args, *kwargs )
            # TODO: can we remove `address`?  The parent has self.address
            self._blinkstick_client = BlinkstickDTO( self._blinkstick_thread, address )

        except Exception as e:
            logging.exception( e )
            raise e


    def _validate_message( self, schema, message ):
        try:
            # TODO: add an environment variable or commandline parameter to
            # disable validation (in case it becomes a performance problem)
            if schema is not None:
                jsonschema.validate( schema=schema, instance=message )
        except jsonschema.exceptions.ValidationError as e:
            logging.error( "Error validating json: %s", e )
        except jsonschema.exceptions.SchemaError as e:
            logging.error( "Error validating schema: %s", e )

    @override
    def send_message( self, data: str | object ):
        if isinstance(data, object):
            self._validate_message( self._send_schema, data )
        super().send_message( json.dumps( data ).encode( "ascii" ) )

    def _update_clients_gauges( self ):
        """ Populates the clients{type=$NAME} prometheus metrics """

        # This function isn't very efficient. There are much better ways to implement. Performance
        # hasn't been a limitation yet.

        total_client_types = CLIENT_TYPES \
                           | set( map( lambda x: self._clients[x].name, self._clients ) )
        for client in total_client_types:
            clients_gauge.labels( client if client is not None else "None" ) \
                        .set( len( list( filter( lambda x: self._clients[x].name == client, self._clients ) ) ) )

    @override
    def handle( self ):
        try:
            if isinstance(self.data, str):
                data = json.loads( self.data )
            else:
                return
            self._validate_message( self._receive_schema, data )

            # {"ping": true} -> {"pong": true}
            if "ping" in data and data["ping"]:
                logging.debug( "Ping!" )
                self.send_message( {"pong": True} )
                return

            # {"enable": "type"} -> {"success": "true|false"}
            if "enable" in data:
                logging.debug( "socket thread enabling %s", data["enable"] )
                self._blinkstick_client.enable( data["enable"] )
                self.send_message( {"success": True } )
                return

            # {"disable": "type"} -> {"success": "true|false"}
            if "disable" in data:
                logging.debug( "socket thread disabling %s", data["disable"] )
                self._blinkstick_client.disable( data["disable"] )
                self.send_message( {"success": True } )
                return

            if "name" in data or "link" in data:
                with self._clients_lock:
                    if "name" in data:
                        self._clients[self.address].name = data["name"]

                    if "link" in data:
                        self._clients[self.address].link = data["link"]
                self.send_message( {"success": True } )


                self._update_clients_gauges()


        except Exception as e:
            logging.exception( e )

    @override
    def connected( self ):
        try:
            logging.debug( "adding client %s", str( self.address ) )
            with self._clients_lock:
                self._clients[self.address] = Client()
                self._update_clients_gauges()
            self._blinkstick_client.register()

        except Exception as e:
            logging.exception( e )

    @override
    def handle_close( self ):
        try:
            with self._clients_lock:
                logging.debug( "removing client %s", str( self.address ) )
                if self.address in self._clients:
                    del self._clients[self.address]
                self._update_clients_gauges()
            self._blinkstick_client.unregister()

        except Exception as e:
            logging.exception( e )


    # TODO: if the thread terminates, remove it from the list of threads in main(), otherwise
    # we'll run out of memory
    # TODO: instead of recording a list of threads and connections, have a set of just active
    # connections?


class LEDController( Application ):
    def __init__(self, args):
        super().__init__(args)
        self._blinkstick_thread = None
        self._clients = {}
        self._clients_lock = threading.Lock()

    @override
    def get_arg_parser( self ) -> argparse.ArgumentParser:
        parser: argparse.ArgumentParser = super().get_arg_parser()
        parser.add_argument('--ws-port',
                            help='The web socket port to bind to',
                            default='9099',
                            dest='ws_port')
        return parser

    def _start_websocket_server(self, blinkstick_thread):
        def start_websocket_server_thread():
            receive_schema = None
            try:
                receive_schema = self._get_schema_from_file(
                    os.path.join( os.path.dirname(__file__), "receive.schema.json") )
            except Exception as e:
                logging.warning("Unable to parse schema file receive.schema.json")
                logging.exception(e)

            send_schema = None
            try:
                send_schema = self._get_schema_from_file(
                    os.path.join( os.path.dirname( __file__ ), "send.schema.json" ) )
            except Exception:
                logging.warning("Unable to parse schema file send.schema.json")

            try:
                address = '0.0.0.0'
                handler = partial(WebSocketHandler,
                                  receive_schema,
                                  send_schema,
                                  blinkstick_thread,
                                  address,
                                  self._clients_lock,
                                  self._clients )
                logging.info("starting websocket handler...")
                server = WebSocketServer( address, self._parsed_args.ws_port, handler )
                server.serve_forever()
            except Exception as e:
                logging.exception( e )
        websocket_thread = threading.Thread( target=start_websocket_server_thread, daemon=True )
        websocket_thread.start()

    @override
    def _get_httpd_handler(self) -> type[http.server.SimpleHTTPRequestHandler]:
        blinkstick_thread = self._blinkstick_thread
        clients = self._clients
        clients_lock = self._clients_lock
        config = self._config

        class HTTPRequestHandler( http.server.SimpleHTTPRequestHandler ):
            @override
            def do_GET( self ): # pylint: disable=invalid-name
                response = None
                status = 500
                headers = {}

                try:
                    current_alerts = None
                    visible_alerts = None
                    if blinkstick_thread is not None:
                        current_alerts = blinkstick_thread.get_current_alerts()
                        visible_alerts = blinkstick_thread.get_visible_alerts()
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
                        + str( visible_alerts ) \
                        + """
                                <br>
                                <br>
                                <h3>Alerts Fired</h3>
                                <pre class="bg-light">""" \
                        + str( current_alerts ) \
                        + """</pre>
                                <h3>Clients</h3>
                                <table class="table"><tr><th>Name</th><th>id</th></tr>"""

                    with clients_lock:
                        for client_id, client in clients.items():
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

                            if link is None:
                                link = ""

                            response += "<tr><td>" + link + "</td><td>" + str( client_id ) + "<td></tr>"

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

        self._blinkstick_thread = BlinkstickThread( self._config )
        self._blinkstick_thread.start()
        self._start_websocket_server( self._blinkstick_thread )

        self._up.set(1)

        assert self._terminate_semaphore is not None
        self._terminate_semaphore.acquire()

        return 0

if __name__ == "__main__":
    # TODO: print a log at start up so the docker logs have a delimiter between
    # launches
    sys.exit( LEDController( sys.argv ).main() )
