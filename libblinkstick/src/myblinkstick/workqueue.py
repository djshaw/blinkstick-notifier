from abc import abstractmethod
import datetime
import logging
import threading

from typing import Iterable, override

from prometheus_client.core import REGISTRY, GaugeMetricFamily
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import Collector

from myblinkstick.heap import HeapBy

def install_workunits_collector( workqueue ):
    class WorkunitsCollector(Collector):
        def __init__( self, workqueue ):
            self._workqueue = workqueue

        @override
        def collect( self ) -> Iterable[Metric]:
            # TODO: concurrent access to workunits?
            return [
                GaugeMetricFamily(
                    'workunit_count',
                    'The number of queued work units',
                    value=self._workqueue.size() ) ]

    REGISTRY.register( WorkunitsCollector( workqueue ) )
    # TODO: add count of successfull and unsuccessful work units executed


class Workunit( object ):
    def __init__( self, dt ):
        self.dt = dt

    @abstractmethod
    def work( self ):
        pass


class WorkQueue( threading.Thread ):
    def __init__( self, *args, **kwargs ):
        self._heap = HeapBy( key=lambda x: x.dt )
        self._lock = threading.Lock()
        self._interrupted = False
        self._event = threading.Event()
        super().__init__( *args, daemon=True, **kwargs )

    def _wait_for_event( self ):
        with self._lock:
            size = self._heap.size()
        if size == 0:
            self._event.clear()
            # Wait for the heap to be non-empty
            if self._interrupted:
                return

            self._event.wait()
            self._event.clear()

            with self._lock:
                assert self._heap.size() > 0 or self._interrupted
                if self._interrupted:
                    return

        wait_time = 0
        while True:
            with self._lock:
                assert self._heap.size() > 0
                workunit = self._heap.peek()

                # The work unit could be in the past or future. If it's in the future, we must wait!
                delta = workunit.dt - datetime.datetime.now()
                wait_time = delta.total_seconds()

            if wait_time > 0:
                self._event.clear()
                self._event.wait( timeout=wait_time )
                # If we're interrupted, we already going to exit. No need to check
                # for _interrupted here
                self._event.clear()
            else:
                # Our wait may have been interruped by a preemting workunit that is in the future
                return


    def run( self ):
        while not self._interrupted:
            try:
                self._wait_for_event()
                if self._interrupted:
                    return

                with self._lock:
                    workunit = self._heap.pop()
                workunit.work()

            except Exception as e:
                logging.exception( e )


    def enqueue( self, workunit ):
        if workunit.dt is None:
            return

        with self._lock:
            self._heap.push( workunit )

        self._event.set()


    def stop( self ):
        self._interrupted = True
        self._event.set()


    def size( self ):
        return self._heap.size()
