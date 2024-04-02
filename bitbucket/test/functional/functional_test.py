import logging
from typing import Any, Tuple
import unittest
import json

import requests
from mock_bitbucket_context import MockBitbucketListener, managed_mock_bitbucket_context
from mock_ledcontroller_context import managed_mock_ledcontroller_context

from process_context import find_free_port, managed_bitbucket_listener
from container_context import managed_mongo


def replace_json(o: dict[str, Any], pattern, replace) -> dict[str, Any]:
    for key, value in o.items():
        if isinstance(value, str):
            o[key] = o[key].replace(pattern, replace)

        if isinstance(value, dict):
            replace_json(o[key], pattern, replace)

    return o

class FunctionalTest( unittest.TestCase ):
    def test_functional( self ):
        class MyBitbucketListener(MockBitbucketListener):
            def __init__(self, http_port: int):
                self._http_port = http_port

            def get_user(self) -> Tuple[int, str]:
                with open( '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleUser.json',
                           'r',
                           encoding='ascii' ) as f:
                    logging.info( "returning sampleUser.json to user query" )
                    # TODO: set response type to application/json
                    return 200, f.read()

            def get_repository(self, repository: str) -> Tuple[int, str]:
                with open('/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleRepository.json',
                          'r',
                          encoding='ascii') as f:
                    logging.info( "returning sampleRepository to repository query" )
                    o = json.loads(f.read())
                    o = replace_json(o,
                                     "https://api.bitbucket.org/",
                                     f"http://127.0.0.1:{self._http_port}/")
                    return 200, json.dumps(o)

            def get_pipelines(self, workspace: str, project: str, page: int) -> Tuple[int, str]:
                file = '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleSingleFailurePipeline.json'
                if page > 1:
                    file = '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleEmptyPipeline.json'

                with open( file, 'r', encoding='ascii' ) as f:
                    logging.info( "returning sampleSingleFailurePipeline.json for pipeline %s in workspace %s",
                                  workspace,
                                  project )
                    return 200, f.read()

        bitbucket_port = find_free_port()
        bitbucket_listener = MyBitbucketListener(bitbucket_port)
        with managed_mongo() as mongo, \
             managed_mock_bitbucket_context(bitbucket_listener, bitbucket_port) as bitbucket, \
             managed_mock_ledcontroller_context() as led_controller, \
             managed_bitbucket_listener(config_file="bitbucket/test/functional/config.yml",
                                        led_controller_url=f"ws://127.0.0.1:{led_controller.ws_port}",
                                        bitbucket_port=bitbucket.httpd_port,
                                        mongo_port=mongo.mongo_port) as bitbucket:
            message = led_controller.queue.get(timeout=10)
            self.assertEqual({"enable": "BitbucketBuildFailure"}, message)
            # TODO: assert {"name": "Bitbucket Listener", "link": "/bitbucket"}

            # TODO: Do I need to set the log level on requests to get this message?
            bitbucket.assert_log(".*\\\"GET /2\\.0/user HTTP\\/1\\.1\\\" 200.*")

            response = requests.get(f"http://127.0.0.1:{bitbucket.http_port}/bitbucket", timeout=10)
            self.assertEqual(200, response.status_code)
