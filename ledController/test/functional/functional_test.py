import unittest
import logging
import json
import threading

import requests
import websocket

from process_context import managed_led_controller

logging.basicConfig( level=logging.DEBUG )

class FunctionalTest( unittest.TestCase ):
    def test_enable_disable( self ):
        with managed_led_controller('ledController/test/config.yml') as led_controller:
            open_sem = threading.Semaphore(0)
            message_sem = threading.Semaphore(0)

            def on_open( ws ):
                open_sem.release()

            def on_message( ws, message ):
                message_sem.release()

            def on_error( ws, error ):
                open_sem.release()
                message_sem.release()

            def on_close( ws, close_code, close_message ):
                open_sem.release()
                message_sem.release()

            # TODO: switch to the blinkstick websocket client?
            ws = websocket.WebSocketApp(
                f"ws://127.0.0.1:{led_controller.ws_port}/",
                on_open=on_open,
                on_close=on_close,
                on_error=on_error,
                on_message=on_message )
            def run_forever():
                try:
                    ws.run_forever()
                except Exception as e:
                    logging.exception(e)
            websocket_app_thread = threading.Thread( daemon=True, target=run_forever )
            websocket_app_thread.start()

            open_sem.acquire()
            ws.send( json.dumps( {"name": "Name"} ).encode("ascii"))
            message_sem.acquire()

            metrics = requests.get(f"http://127.0.0.1:{led_controller.prometheus_port}/metrics", timeout=10)
            text = metrics.text
            # TODO: Find a prometheus library that will process the /metrics result
            self.assertRegex(text, ".*clients{type=\"Name\"} 1.0.*")

            # TODO: disconnect the websocket and verify that the client no longer exists (or the value is 0)
