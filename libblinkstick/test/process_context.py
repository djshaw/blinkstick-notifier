from contextlib import contextmanager, closing
import os
import signal
import subprocess
import time
import socket
import requests

def find_free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

@contextmanager
def managed_process( *args, **kwargs ):
    p = None

    try:
        p = subprocess.Popen(*args, preexec_fn=os.setsid, **kwargs)
        yield p
    finally:
        if p is not None:
            p.poll()

            if p.returncode is None:
                # TODO: call p.terminate() first, to give the process an opportunity to clean up
                # after itself
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)

class ManagedPrometheus:
    def __init__(self, process, prometheus_port):
        self.process = process
        self.prometheus_port = prometheus_port

@contextmanager
def managed_process_with_prometheus_monitoring( *args, prometheus_port: int=None ):
    if prometheus_port is None:
        i: int = 0
        while i < len(args[0]):
            if args[0][i] == "--prometheus-port":
                if i + 1 < len(args[0]):
                    prometheus_port = int(args[0][i+1])
                    break
            i += 1
    if prometheus_port is None:
        prometheus_port = 9000
    assert prometheus_port >= 1024 and prometheus_port < 65535
    with managed_process( *args ) as p:
        while True:
            text = ""
            try:
                metrics = requests.get(f"http://127.0.0.1:{prometheus_port}/metrics", timeout=10)
                text = metrics.text
            except requests.exceptions.ConnectionError:
                pass
            # TODO: Find a prometheus library that will process the /metrics result
            if text.find("up 1.0") != -1:
                break

            # Don't slam the system by checking prometheus as fast as possible
            time.sleep(1)
        yield ManagedPrometheus(p, prometheus_port)

class ManagedApplication(ManagedPrometheus):
    def __init__(self,
                 process,
                 prometheus_port: int,
                 http_port: int):
        super().__init__(process, prometheus_port)
        self.http_port = http_port

class ManagedLEDController(ManagedApplication):
    def __init__(self, process, prometheus_port, http_port, ws_port):
        super().__init__(process, prometheus_port, http_port)
        self.ws_port = ws_port

@contextmanager
def managed_led_controller():
    prometheus_port: int=find_free_port()
    http_port: int=find_free_port()
    ws_port: int=find_free_port()
    with managed_process_with_prometheus_monitoring(["python3",
                                                     "./ledController/src/ledController.py",
                                                     "--prometheus-port", str(prometheus_port),
                                                     "--ws-port", str(ws_port),
                                                     "--http-port", str(http_port)]) as p:
        yield ManagedLEDController(p.process, p.prometheus_port, http_port, ws_port=ws_port)

@contextmanager
def managed_webhook(led_controller_url: str, config_file: str):
    prometheus_port: int=find_free_port()
    http_port: int=find_free_port()
    with managed_process_with_prometheus_monitoring(["python3",
                                                     "./webhook/src/webhook_listener.py",
                                                     "--led-controller-url", led_controller_url,
                                                     "--config", config_file,
                                                     "--prometheus-port", str(prometheus_port),
                                                     "--http-port", str(http_port)]) as p:
        yield ManagedApplication(p.process, p.prometheus_port, http_port)


class ManagedBitbucket(ManagedApplication):
    def __init__(self, process, prometheus_port: int, http_port: int, mongo_port: int):
        super().__init__(process, prometheus_port, http_port)
        self.mongo_port = mongo_port


@contextmanager
def managed_bitbucket(led_controller_url: str,
                      config_file: str,
                      prometheus_port: int = None,
                      http_port: int = None,
                      bitbucket_port: int = None,
                      mongo_port: int = None):
    if mongo_port is None:
        mongo_port = find_free_port()
    if prometheus_port is None:
        prometheus_port = find_free_port()
    if http_port is None:
        http_port = find_free_port()
    if prometheus_port is None:
        prometheus_port = find_free_port()
    with managed_process_with_prometheus_monitoring(["python3", "/workspaces/blinkstick-notifier/bitbucket/src/bitbucket_listener.py",
                            "--prometheus-port",    str(prometheus_port),
                            "--led-controller-url", led_controller_url,
                            "--bitbucket-url",      f"http://127.0.0.1:{bitbucket_port}",
                            "--mongo-url",          f"mongodb://127.0.0.1:{mongo_port}/bitbucket",
                            "--http-port",          str(http_port),
                            "--config",             config_file]) as p:
        yield ManagedBitbucket(p.process, p.prometheus_port, http_port, mongo_port)

@contextmanager
def managed_calendar_listener():
    http_port = find_free_port()
    prometheus_port = find_free_port()
    with managed_process_with_prometheus_monitoring(
        ["python3", "/workspaces/blinkstick-notifier/calendarListener/src/calendarListener.py",
         "--prometheus-port", str(prometheus_port),
         "--http-port",       str(http_port)]) as p:
        yield ManagedApplication(p.process, p.prometheus_port, http_port)

@contextmanager
def managed_outlook_listener():
    http_port = find_free_port()
    prometheus_port = find_free_port()
    with managed_process_with_prometheus_monitoring(
        ["python3", "/workspaces/blinkstick-notifier/outlookListener/src/outlookListener.py",
         "--prometheus-port",  str(prometheus_port),
         "--http-port",        str(http_port),
         "--credentials-file", "secrets/outlookListener/credentials.yaml"]) as p:
        yield ManagedApplication(p.process, p.prometheus_port, http_port)
