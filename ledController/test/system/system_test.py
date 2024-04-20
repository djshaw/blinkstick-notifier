import json
import logging
from typing import Tuple, override
import unittest

import requests
from container_context import managed_mongo
from mock_bitbucket_context import MockBitbucketListener, managed_mock_bitbucket_context

from process_context import managed_bitbucket_listener, managed_calendar_listener, managed_led_controller

class SystemTest(unittest.TestCase):
    def test_calendar_listener(self):
        with managed_led_controller('ledController/test/config.yml') as led_controller, \
             managed_calendar_listener(f"ws://127.0.0.1:{led_controller.ws_port}",
                                       "calendarListener/tests/config.yml"):
            # Check that the led-controller has a calendarListener client
            metrics = requests.get(f"http://127.0.0.1:{led_controller.prometheus_port}/metrics", timeout=10)
            text = metrics.text
            # TODO: Find a prometheus library that will process the /metrics result
            # TODO: make a const for the client name
            self.assertRegex(text, ".*clients{type=\"Calendar Listener\"} 1.0.*")

    def test_bitbucket_listener(self):
        class MyBitbucketListener(MockBitbucketListener):
            @override
            def get_user(self) -> Tuple[int, str]:
                with open( '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleUser.json',
                           'r',
                           encoding='ascii' ) as f:
                    logging.info( "returning sampleUser.json to user query" )
                    # TODO: set response type to application/json
                    return 200, json.loads(f.read())

            @override
            def get_repository(self, repository: str) -> Tuple[int, str]:
                with open( '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleRepository.json',
                           'r',
                           encoding='ascii' ) as f:
                    return 200, json.loads(f.read())

            @override
            def get_pipelines(self, workspace: str, project: str, page: int) -> Tuple[int, str]:
                with open( '/workspaces/blinkstick-notifier/bitbucket/test/functional/sampleEmptyPipeline.json',
                           'r',
                           encoding='ascii' ) as f:
                    return 200, json.loads(f.read())
        bitbucket_listener = MyBitbucketListener()

        with managed_led_controller('ledController/test/config.yml') as led_controller, \
             managed_mock_bitbucket_context(bitbucket_listener) as mock_bitbucket, \
             managed_mongo() as mongo, \
             managed_bitbucket_listener(f"ws://127.0.0.1:{led_controller.ws_port}",
                                        config_file="bitbucket/test/functional/config.yml",
                                        mongo_port=mongo.mongo_port,
                                        bitbucket_port=mock_bitbucket.httpd_port):
            metrics = requests.get(f"http://127.0.0.1:{led_controller.prometheus_port}/metrics", timeout=10)
            text = metrics.text
            self.assertRegex(text, ".*clients{type=\"Bitbucket Listener\"} 1.0.*")
