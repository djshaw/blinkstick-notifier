from contextlib import contextmanager, closing
import os
import re
import signal
import subprocess
import time
import socket
from typing import Any, Generator, List
import requests

from log_monitoring import LogMonitor

def find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

class ManagedProcess:
    def __init__(self, process: subprocess.Popen, allowed_log_lines: List[re.Pattern] | None=None):
        self.process = process
        # When the process is stopped, the blocking readline() will return None
        self.log_monitor = LogMonitor(process, allowed_log_lines)
        self.log_monitor.name = 'LogMonitor'
        self.log_monitor.start()

@contextmanager
def managed_process( *args,
                     allowed_log_lines: List[re.Pattern] | None=None,
                     **kwargs ) -> Generator[ManagedProcess, Any, None]:
    p = None

    try:
        p = subprocess.Popen(
            *args,
            # When debugging, a child process remains open, preventing the test from terminating
            preexec_fn=os.setsid,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs)
        result = ManagedProcess(p, allowed_log_lines)
        yield result
        result.log_monitor.assert_no_bad_logs()
    finally:
        if result.log_monitor is not None and result.log_monitor.is_alive():
            result.log_monitor.interrupt()
            result.log_monitor.join(timeout=5)
            # TODO: check for timeout
        if p is not None:
            p.poll()

            if p.returncode is None:
                # TODO: call p.terminate() first, to give the process an opportunity to clean up
                # after itself
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)

class ManagedPrometheus:
    def __init__(self, process: ManagedProcess, prometheus_port: int):
        self.process: ManagedProcess = process
        self.prometheus_port: int = prometheus_port


@contextmanager
def managed_process_with_prometheus_monitoring(
        *args,
        prometheus_port: int | None=None,
        allowed_log_lines: List[re.Pattern] | None=None,
        **kwargs ) -> Generator[ManagedPrometheus, Any, None]:
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
    with managed_process( *args, allowed_log_lines=allowed_log_lines, **kwargs ) as p:
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
                 process: ManagedProcess,
                 prometheus_port: int,
                 http_port: int):
        super().__init__(process, prometheus_port)
        self.http_port: int = http_port

    def assert_log(self, message_pattern: str) -> None:
        self.process.log_monitor.assert_log(message_pattern)

class ManagedLEDController(ManagedApplication):
    def __init__(self, process, prometheus_port, http_port, ws_port):
        super().__init__(process, prometheus_port, http_port)
        self.ws_port = ws_port

@contextmanager
def managed_led_controller(config_file: str) -> Generator[ManagedLEDController, Any, None]:
    prometheus_port: int = find_free_port()
    http_port: int = find_free_port()
    ws_port: int = find_free_port()
    with managed_process_with_prometheus_monitoring(
        ["python3",
         "./ledController/src/ledController.py",
         "--config",          config_file,
         "--prometheus-port", str(prometheus_port),
         "--ws-port",         str(ws_port),
         "--http-port",       str(http_port)],
        allowed_log_lines=[re.compile(".*no blinksticks found!")]) as p:
        yield ManagedLEDController(p.process, p.prometheus_port, http_port, ws_port=ws_port)

@contextmanager
def managed_webhook(led_controller_url: str, config_file: str) -> Generator[ManagedApplication, Any, None]:
    prometheus_port: int=find_free_port()
    http_port: int=find_free_port()
    with managed_process_with_prometheus_monitoring(
        ["python3",
         "./webhook/src/webhook_listener.py",
         "--led-controller-url", led_controller_url,
         "--config",             config_file,
         "--prometheus-port",    str(prometheus_port),
         "--http-port",          str(http_port)],
        allowed_log_lines=[re.compile(".*Unable to find config schema file (.*/)?config.schema.json")]) as p:
        yield ManagedApplication(p.process, p.prometheus_port, http_port)


class ManagedBitbucket(ManagedApplication):
    def __init__(self,
                 process: ManagedProcess,
                 prometheus_port: int,
                 http_port: int,
                 mongo_port: int):
        super().__init__(process, prometheus_port, http_port)
        self.mongo_port = mongo_port


@contextmanager
def managed_bitbucket_listener(led_controller_url: str,
                               config_file: str,
                               prometheus_port: int | None = None,
                               http_port: int | None = None,
                               bitbucket_port: int | None = None,
                               mongo_port: int | None = None) -> Generator[ManagedBitbucket, Any, None]:
    if mongo_port is None:
        mongo_port = find_free_port()
    if prometheus_port is None:
        prometheus_port = find_free_port()
    if http_port is None:
        http_port = find_free_port()
    env = os.environ.copy()
    env["DEFAULT_LOG_LEVEL"] = "DEBUG"
    with managed_process_with_prometheus_monitoring(
            ["python3", "bitbucket/src/bitbucket_listener.py",
            "--prometheus-port",    str(prometheus_port),
            "--led-controller-url", led_controller_url,
            "--bitbucket-url",      f"http://127.0.0.1:{bitbucket_port}",
            "--mongo-url",          f"mongodb://127.0.0.1:{mongo_port}/bitbucket",
            "--http-port",          str(http_port),
            "--config",             config_file],
            env=env) as p:
        yield ManagedBitbucket(p.process, p.prometheus_port, http_port, mongo_port)

@contextmanager
def managed_calendar_listener(led_controller_url: str,
                              config_file: str,
                              prometheus_port: int | None = None,
                              http_port: int | None = None) -> Generator[ManagedApplication, Any, None]:
    if http_port is None:
        http_port = find_free_port()
    if prometheus_port is None:
        prometheus_port = find_free_port()
    with managed_process_with_prometheus_monitoring(
        ["python3", "/workspaces/blinkstick-notifier/calendarListener/src/calendarListener.py",
                    "--led-controller-url", led_controller_url,
                    "--prometheus-port",    str(prometheus_port),
                    "--http-port",          str(http_port),
                    "--config",             config_file]) as p:
        yield ManagedApplication(p.process, p.prometheus_port, http_port)

@contextmanager
def managed_outlook_listener(config_file: str, credentials_file: str) -> Generator[ManagedApplication, Any, None]:
    http_port = find_free_port()
    prometheus_port = find_free_port()
    with managed_process_with_prometheus_monitoring(
        ["python3", "/workspaces/blinkstick-notifier/outlookListener/src/outlookListener.py",
                    "--config",           config_file,
                    "--prometheus-port",  str(prometheus_port),
                    "--http-port",        str(http_port),
                    "--credentials-file", credentials_file],
        allowed_log_lines=[re.compile(".*no blinksticks found!")]) as p:
        yield ManagedApplication(p.process, p.prometheus_port, http_port)
