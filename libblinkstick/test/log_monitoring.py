import functools
import queue
import re
import select
from subprocess import Popen
import threading
from typing import List

BAD_LOGS_PATTERNS = [re.compile("^warning", re.IGNORECASE),
                     re.compile("^error", re.IGNORECASE)]
class LogMonitor(threading.Thread):
    def __init__(self, process: Popen,
                 allowed_log_lines: List[re.Pattern] | None=None):
        super().__init__()
        self._process = process
        self._log_queue = queue.Queue()
        if allowed_log_lines is not None:
            self._allowed_log_lines = allowed_log_lines
        else:
            self._allowed_log_lines = []
        self._bad_log_lines = []
        self._interrupted = False

    def run(self) -> None:
        while True:
            ready = select.select([self._process.stdout], [], [], 0.1)[0]
            if not ready:
                if self._interrupted:
                    break
            else:
                for i in ready:
                    line = i.readline()
                    if len(ready) == 0:
                        if self._interrupted:
                            break
                        continue
                    if isinstance(line, bytes):
                        line = line.decode("ascii")
                    if line is None or line == '':
                        continue
                    if len(line) > 0 and line[-1] == "\n":
                        line = line[:len(line)-1]
                    self._log_queue.put(line)

    def interrupt(self) -> None:
        self._interrupted = True

    def _check_for_a_bad_log(self, line) -> bool:
        """ Returns True iff the log line matches any of the BAD_LOGS_PATTERNS """
        # Just to make typechecking easier
        def _or(a: bool, b: bool) -> bool:
            return a or b
        return not functools.reduce(_or,
                                    map(lambda pattern: pattern.match(line) is not None,
                                        self._allowed_log_lines),
                                    False) and \
               functools.reduce(_or,
                                map(lambda pattern: pattern.match(line) is not None,
                                    BAD_LOGS_PATTERNS))

    def assert_no_bad_logs(self) -> None:
        """ Verifies that there are no warning or error log messages"""
        while not self._log_queue.empty():
            line = self._log_queue.get_nowait()
            if self._check_for_a_bad_log(line):
                self._bad_log_lines.append(line)
        if len(self._bad_log_lines) > 0:
            raise AssertionError(f"Found bad log lines: {str(self._bad_log_lines)}")

    def assert_log(self, message_pattern: str) -> None:
        pattern = re.compile(message_pattern)
        while True:
            line = self._log_queue.get(block=True, timeout=10)
            if self._check_for_a_bad_log(line):
                self._bad_log_lines.append(line)
            if pattern.match(line) is not None:
                return
            if line is None:
                raise AssertionError(f"Cannot file log message matching `{message_pattern}`")
