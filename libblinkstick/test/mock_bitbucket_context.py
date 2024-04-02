from abc import abstractmethod
from contextlib import contextmanager
from functools import partial
import http
import http.server
from http.server import BaseHTTPRequestHandler
import json
import logging
import re
import threading
from typing import Any, Generator, Tuple

from process_context import find_free_port

class MockBitbucketListener:
    @abstractmethod
    def get_user(self) -> Tuple[int, str]:
        pass

    @abstractmethod
    def get_repository(self, repository: str) -> Tuple[int, str]:
        pass

    @abstractmethod
    def get_pipelines(self, workspace: str, project: str, page: int) -> Tuple[int, str]:
        pass

class HTTPRequestHandler( BaseHTTPRequestHandler ):
    # TODO: we could combine these into the same regex
    REPOSITORIES_REGEX = re.compile("/2.0/repositories/([a-zA-Z-]*)/([a-zA-Z0-9-]*)(\\?.*)?$")
    PIPELINES_REGEX    = re.compile("/2.0/repositories/([a-zA-Z-]*)/([a-zA-Z0-9-]*)/pipelines/(\\?.*)?$")
    PAGE_REGEX         = re.compile(".*page=(\\d).*")

    def __init__(self,
                 httpd_port: int,
                 listener: MockBitbucketListener,
                 *args,
                 **kwargs):
        self._listener = listener
        self._httpd_port = httpd_port
        super().__init__(*args, **kwargs)

    def _replace_json(self, o: dict[str, Any], pattern, replace) -> dict[str, Any]:
        for key, value in o.items():
            if isinstance(value, str):
                o[key] = o[key].replace(pattern, replace)

            if isinstance(value, dict):
                self._replace_json(o[key], pattern, replace)

        return o

    def _update_bitbucket_url(self, o: dict[str, Any]) -> dict[str, Any]:
        return self._replace_json(o, "https://api.bitbucket.org/", f"http://127.0.0.1:{self._httpd_port}/")


    def do_GET( self ): # pylint: disable=invalid-name
        response = None
        status = 500
        headers = {}

        o = None
        try:
            # TODO: the test should dictate which files are returned
            if o is None:
                if self.path == "/2.0/user":
                    status, o = self._listener.get_user()

            if o is None:
                m = self.REPOSITORIES_REGEX.match(self.path)
                if m is not None:
                    status, o = self._listener.get_repository(m.group(1))

            if o is None:
                m = self.PIPELINES_REGEX.match(self.path)
                if m is not None:
                    page = 1
                    page_match = self.PAGE_REGEX.match(self.path)
                    if page_match is not None:
                        page = int(page_match.group(1))
                    status, o = self._listener.get_pipelines(m.group(1), m.group(2), page)

            if o is not None and isinstance(o, str):
                response = json.dumps(self._update_bitbucket_url(json.loads(o)))
                print(response)
            else:
                response = ""

        finally:
            self.send_response( status )
            for key, value in headers.items():
                self.send_header( key, value )
            self.end_headers()
            if response is not None:
                if isinstance( response, str ):
                    response = response.encode( "utf-8" )
                self.wfile.write( response )


class MockBitbucket:
    def __init__(self, httpd_port: int):
        self.httpd_port = httpd_port

@contextmanager
def managed_mock_bitbucket_context(listener: MockBitbucketListener,
                                   httpd_port: int | None = None) -> Generator[MockBitbucket, Any, None]:
    if httpd_port is None:
        httpd_port = find_free_port()

    def start_websocket_server():
        try:
            handler = partial(HTTPRequestHandler, httpd_port, listener)
            httpd = http.server.HTTPServer(('0.0.0.0', httpd_port), handler )
            httpd.serve_forever()
        except Exception as e:
            logging.exception(e)

    httpd_thread = threading.Thread(target=start_websocket_server, daemon=True)
    httpd_thread.start()

    yield MockBitbucket(httpd_port)

    # TODO: need a way to kill the mock websocket server!
