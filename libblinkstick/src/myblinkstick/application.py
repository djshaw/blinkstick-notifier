from abc import abstractmethod
import argparse
import inspect
import logging
import sys
import threading
import signal
import json
import os
import http
import http.server

from typing import Iterable, override

import jsonschema
import jsonschema.exceptions
import yaml

from myblinkstick.websocket_client import WebsocketClient
from myblinkstick.workqueue import WorkQueue, install_workunits_collector

from prometheus_client.registry import Collector
from prometheus_client.core import GaugeMetricFamily, REGISTRY
from prometheus_client.metrics_core import Metric
from prometheus_client import start_http_server, Gauge

# TODO: better name for `myblinkstick`

class Application:
    def __init__( self, args ):
        self._args = args
        self._parsed_args = self.get_arg_parser().parse_args(self._args[1:])
        self.setup_logging()

        config_schema = \
            os.path.join(
                os.path.dirname(inspect.getfile(self.__class__)),
                "config.schema.json")
        self._config = self._get_config(config_filename=self._parsed_args.config_file,
                                        schema_filename=config_schema)
        self._up = Gauge(
            'up',
            'Whether or not the ledController is running' )
        self._up.set( 0 )
        self._terminate_semaphore = None

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

    def _get_resource_file_contents( self, file_path: str ) -> str:
        if os.path.exists( file_path ):
            with open( file_path, 'r', encoding='ascii' ) as f:
                return f.read()
        raise FileNotFoundError( f"Could not file resource file {file_path}" )

    def _get_yaml_resource_file_contents( self, file_path: str ) -> object:
        return yaml.safe_load(self._get_resource_file_contents(file_path))

    def _get_schema_from_file( self, file_path ) -> object | str | None:
        try:
            content = self._get_resource_file_contents(file_path)
            if file_path.endswith('.json'):
                return json.loads(content)

            logging.info(file_path.ends_with('.yaml'))
            if file_path.endswith('.yaml') or file_path.ends_with('.yml'):
                return yaml.safe_load(content)

            logging.warning("unable to identify the content of resource file %s", file_path)
            return content
        except Exception:
            logging.warning("Unable to load schema file %s", file_path)
            return None

    # TODO: unit test
    # TODO: pass in parsed args
    # TODO: check for environment variables?
    def _get_config( self, config_filename, schema_filename ) -> dict:
        # TODO: abstract out loading and validating of config.yml
        config = None
        if config_filename is not None:
            config = self._get_yaml_resource_file_contents(config_filename)
        if config is None:
            logging.warning( "Using an empty config file" )
            config = {}

        if schema_filename is not None and os.path.exists( schema_filename ):
            schema = self._get_schema_from_file(schema_filename)
            if not isinstance(schema, object):
                logging.warning("Unable to load schema file %s", schema_filename)

            # Purposefully only log an error. We want to continue to run if we can.
            else:
                try:
                    jsonschema.validate(instance=config, schema=schema) # type: ignore
                except jsonschema.exceptions.ValidationError as e:
                    logging.error( "Error validating json: %s", e )
                except jsonschema.exceptions.SchemaError as e:
                    logging.error( "Error validating schema: %s", e )
        else:
            logging.warning( "Unable to find config schema file %s", schema_filename )

        logging.info(config)
        logging.info(type(config))
        assert isinstance(config, dict)
        return config


    def install_signal_handler(self):
        terminate_semaphore = threading.Semaphore(0)
        def signal_handler( signum, frame ):
            if signum in [ signal.SIGINT, signal.SIGTERM ]:
                terminate_semaphore.release()
        signal.signal( signal.SIGINT,  signal_handler )
        signal.signal( signal.SIGTERM, signal_handler )

        return terminate_semaphore

    def get_command_line_arguments(self):
        pass

    def setup_collector(self):
        class CustomCollector(Collector):
            @override
            def collect( self ) -> Iterable[Metric]:
                return [
                    GaugeMetricFamily(
                        'python_threads',
                        'The number of threads reported by python\'s threading.active_count()',
                        value=threading.active_count())]

        REGISTRY.register(CustomCollector())

    def setup_logging(self):
        def set_log_level_from_environment(logger: str, envvar: str | None= None):
            if envvar is None:
                envvar = f"{logger.upper()}_LOG_LEVEL"
            default_level = os.environ.get(envvar, 'info').upper()
            level = logging.getLevelName(default_level)
            if isinstance(level, int):
                logging.getLogger(logger).setLevel(level=level)
            else:
                logging.warning("Unexpected log level `%s` for `%s`", logger, envvar)

        default_level = os.environ.get('DEFAULT_LOG_LEVEL', 'info').upper()
        if isinstance(logging.getLevelName(default_level), int):
            print(f"setting default logging to {default_level}")
            logging.basicConfig(level=logging.getLevelName(default_level))

        set_log_level_from_environment("requests.packages.urllib3", "REQUESTS_LOG_LEVEL")

        for key in \
            filter( lambda x: x.endswith( '_LOG_LEVEL' ) and x != 'DEFAULT_LOG_LEVEL',
                    os.environ ):

            if not isinstance(logging.getLevelName(os.environ[key].upper()), int):
                continue

            # TODO: implement the logging challengs
            if key.lower() in ["bitbucket", "google", "outlook"]:
                logging.getLogger(key.replace('_LOG_LEVEL$', '')).setLevel(
                    level=logging.getLevelName(os.environ[key].upper()))

        # Remove the default logger. It allows log messages to contain a new line
        logging.getLogger().handlers = []

        class LogFormatter( logging.Formatter ):
            def __init__( self, fmt=None, datefmt=None ):
                super().__init__( fmt=fmt, datefmt=datefmt )
                self.string_formatter = logging.Formatter( "%(levelname)s:%(name)s:%(message)s" )

            @override
            def format( self, record ) -> str:
                return self.string_formatter.format( record ).replace( "\n", "\\n" )
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(LogFormatter())
        logging.getLogger().addHandler(handler)

        def custom_hook( args ):
            logging.exception( args )
        threading.excepthook = custom_hook

    @abstractmethod
    def _get_httpd_handler(self) -> type[http.server.SimpleHTTPRequestHandler]:
        pass

    def start_http_server(self):
        def httpd_service():
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
    def __init__( self, args, sensor_name: str, http_path_prefix: str ):
        super().__init__( args )
        self._sensor_name = sensor_name
        self._http_path_prefix = http_path_prefix
        self._ws = None
        self._workqueue = None

    @abstractmethod
    @override
    def _get_httpd_handler(self) -> type[http.server.SimpleHTTPRequestHandler]:
        pass

    @override
    def get_arg_parser(self) -> argparse.ArgumentParser:
        parser = super().get_arg_parser()
        parser.add_argument('--led-controller-url',
                            help='The url of the led-controller',
                            default='ws://led-controller:9099/', # TODO: use a url object
                            dest='led_controller_url')
        return parser

    def get_http_path_prefix( self ):
        return self._http_path_prefix

    def start_websocket_client( self ) -> WebsocketClient:
        if self._ws is None:
            self._ws = WebsocketClient( self._parsed_args.led_controller_url,
                                        name=self._sensor_name,
                                        httpPathPrefix=self.get_http_path_prefix() )
            self._ws.start()
        return self._ws

    def start_work_queue(self):
        self._workqueue = WorkQueue()
        install_workunits_collector( self._workqueue )
        self._workqueue.start()

    @override
    def main(self) -> int:
        result = super().main()
        if result != 0:
            return result
        # TODO: don't set the `up` metric until a websocket connection is established (or create a
        # `connected` metric)
        self.start_websocket_client()
        self.start_work_queue()

        return 0
