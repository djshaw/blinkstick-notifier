import logging
from typing import Tuple
import unittest
import json

import requests
from mock_bitbucket_context import MockBitbucketListener, managed_mock_bitbucket_context
from mock_ledcontroller_context import managed_mock_ledcontroller_context

from process_context import managed_bitbucket_listener
from container_context import managed_mongo




class FunctionalTest( unittest.TestCase ):
    def test_functional( self ):
        class MyBitbucketListener(MockBitbucketListener):
            def get_user(self) -> Tuple[int, str]:
                with open( '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleUser.json',
                           'r',
                           encoding='ascii' ) as f:
                    logging.info( "returning sampleUser.json to user query" )
                    # TODO: set response type to application/json
                    return 200, json.loads(f.read())

            def get_repository(self, repository: str) -> Tuple[int, str]:
                with open('/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleRepository.json',
                          'r',
                          encoding='ascii') as f:
                    logging.info( "returning sampleRepository to repository query" )
                    return 200, json.loads(f.read())

            def get_pipelines(self, workspace: str, project: str, page: int) -> Tuple[int, str]:
                file = '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleSingleFailurePipeline.json'
                if page > 1:
                    file = '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleEmptyPipeline.json'

                with open( file, 'r', encoding='ascii' ) as f:
                    logging.info( "returning sampleSingleFailurePipeline.json for pipeline %s in workspace %s",
                                  workspace,
                                  project )
                    return 200, json.loads(f.read())

        bitbucket_listener = MyBitbucketListener()
        with managed_mongo() as mongo, \
             managed_mock_bitbucket_context(bitbucket_listener) as bitbucket, \
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
