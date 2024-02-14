import argparse
import logging
import threading
import signal
import json
import os
import http
from http.server import BaseHTTPRequestHandler

from typing import Iterable

import jsonschema
import yaml

from myblinkstick.websocket_client import WebsocketClient
from myblinkstick.workqueue import WorkQueue, installWorkunitsCollector

from prometheus_client.core import GaugeMetricFamily, REGISTRY
from prometheus_client.metrics_core import Metric
from prometheus_client import start_http_server, Gauge

# TODO: better name for `myblinkstick`

class Application:
    def __init__( self, args ):
        self._args = args
        self._parsed_args = self.get_arg_parser().parse_args(self._args[1:])
        self._config = self._get_config(config_filename=self._parsed_args.config_file)
        self._up = Gauge(
            'up',
            'Whether or not the ledController is running' )
        self._up.set( 0 )
        self._terminate_semaphore = None
        self.setup_logging()

    def start_prometheus( self ):
        start_http_server( int( self._parsed_args.prometheus_port ) )

    def get_arg_parser( self ) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="Webhook Listener",
            description="Listens for webhook callbacks from alertmanager and converts them to blinkstick conditions")
        parser.add_argument('-c', '--config',
                            help='Path to config file',
                            default='config.yml',
                            dest='config_file')
        parser.add_argument('--prometheus-port',
                            help='The port the prometheus client will bind to',
                            default='9000',
                            dest='prometheus_port')
        parser.add_argument('--http-port',
                            help='The port the http server will bind to',
                            default='8080',
                            dest='http_port')
        return parser

    # TODO: unit test
    # TODO: pass in parsed args
    # TODO: check for environment variables?
    def _get_config( self, config_filename="config.yml", schema_filename="config.schema.json" ):
        # TODO: abstract out loading and validating of config.yml
        config = {}
        if config_filename is not None:
            if os.path.exists( config_filename ):
                try:
                    with open( config_filename, 'r', encoding="ascii" ) as f:
                        config = yaml.safe_load( f )
                except Exception as e:
                    logging.error( "Unable to read and parse config file %s", config_filename )
                    logging.exception( e )
            else:
                logging.warning( "Unable to find config file %s", config_filename )
        else:
            logging.warning( "Using an empty config file" )

        if schema_filename is not None and os.path.exists( schema_filename ):
            with open( schema_filename, 'r', encoding='ascii') as f:
                schema = json.load( f )

                # Purposefully only log an error. We want to continue to run if we can.
                try:
                    jsonschema.validate(instance=config, schema=schema)
                except jsonschema.exceptions.ValidationError as e:
                    logging.error( "Error validating json: %s", e )
                except jsonschema.exceptions.SchemaError as e:
                    logging.error( "Error validating schema: %s", e )
        else:
            logging.warning( "Unable to find config schema file %s", schema_filename )

        return config


    def install_signal_handler(self):
        terminate_semaphore = threading.Semaphore(0)
        def signal_handler( signum, frame ):
            if signum == signal.SIGINT or signum == signal.SIGTERM:
                terminate_semaphore.release()
        signal.signal( signal.SIGINT,  signal_handler )
        signal.signal( signal.SIGTERM, signal_handler )

        return terminate_semaphore

    def get_command_line_arguments(self):
        pass

    def setup_collector(self):
        class CustomCollector:
            def collect( self ) -> Iterable[Metric]:
                return [
                    GaugeMetricFamily(
                        'python_threads',
                        'The number of threads reported by python\'s threading.active_count()',
                        value=threading.active_count())]

        REGISTRY.register( CustomCollector() )

    def setup_logging(self):
        logging.basicConfig( level=logging.getLevelName(os.environ.get('DEFAULT_LOG_LEVEL', 'info').upper()) )

        for key in \
            filter( lambda x: x.endswith( '_LOG_LEVEL' ) and x != 'DEFAULT_LOG_LEVEL', 
                    os.environ ):
            if not isinstance(logging.getLevelName(os.environ[key].upper()), int):
                continue
            logging.getLogger(key.replace('_LOG_LEVEL$', '')).setLevel(
                level=logging.getLevelName(os.environ[key].upper()))

        # Remove the default logger. It allows log messages to contain a new line
        logging.getLogger('').handlers = []

        class LogFormatter( logging.Formatter ):
            def __init__( self, fmt=None, datefmt=None ):
                super().__init__( fmt=fmt, datefmt=datefmt )
                self.string_formatter = logging.Formatter( "%(levelname)s:%(name)s:%(message)s" )

            def format( self, record ):
                return self.string_formatter.format( record ).replace( "\n", "\\n" )
        handler = logging.StreamHandler()
        handler.setFormatter( LogFormatter() )
        logging.getLogger('').addHandler( handler )

        def custom_hook( args ):
            logging.exception( args )
        threading.excepthook = custom_hook

    def _get_httpd_handler(self) -> BaseHTTPRequestHandler:
        raise Exception('Not implemented')

    def start_http_server(self):
        def httpd_service():
            # TODO: make port configurable
            httpd = http.server.HTTPServer( ('', int(self._parsed_args.http_port)), self._get_httpd_handler() )
            httpd.serve_forever()
        httpd = threading.Thread( daemon=True, target=httpd_service )
        httpd.start()

    def main(self) -> int:
        self._terminate_semaphore = self.install_signal_handler()
        self.setup_collector()
        self.start_prometheus()
        self.start_http_server()

        return 0

class Sensor( Application ):
    def __init__( self, args, sensor_name, http_path_prefix ):
        super().__init__( args )
        self._sensor_name = sensor_name
        self._http_path_prefix = http_path_prefix
        self._ws = None
        self._workqueue = None

    def get_arg_parser(self):
        parser = super().get_arg_parser()
        parser.add_argument('--led-controller-url',
                            help='The url of the led-controller',
                            default='ws://led-controller:9099/', # TODO: use a url object
                            dest='led_controller_url')
        return parser

    def get_http_handler( self ):
        raise Exception('Not implemented')

    def get_http_path_prefix( self ):
        return self._http_path_prefix

    def start_websocket_client( self ):
        if self._ws is None:
            self._ws = WebsocketClient( self._parsed_args.led_controller_url,
                                        name=self._sensor_name,
                                        httpPathPrefix=self.get_http_path_prefix() )
            self._ws.start()
        return self._ws

    def start_work_queue(self):
        self._workqueue = WorkQueue()
        installWorkunitsCollector( self._workqueue )
        self._workqueue.start()

    def main(self) -> int:
        result = super().main()
        if result != 0:
            return result
        self.start_websocket_client()
        self.start_work_queue()

        return 0
