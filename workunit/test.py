import datetime
import threading
import time
import unittest

import workunit

class LambdaWorkunit( workunit.Workunit ):
    def __init__( self, datetime, *args, **kwargs ):
        super().__init__( datetime, *args, **kwargs )
        self.fail = False
        self.fired = False
        self.sem = threading.Semaphore( 0 )

    def work( self ):
        self.fired = True
        now = datetime.datetime.now()
        if now < self.dt:
            self.fail = True
        self.sem.release()

class WorkQueueTest( unittest.TestCase ):
    def __init__( self, *args, **kwargs ):
        super().__init__( *args, **kwargs )

    # When one work unit preempts another, the work queue wakes up and processes the preemtive work
    # unit
    def test_preempt( self ):
        workqueue = None

        try:
            workqueue = workunit.WorkQueue()
            workqueue.start()

            # Give the queue plenty of time to start, to make sure we exercise the zero length heap
            # condition
            time.sleep( 0.5 )

            sem = threading.Semaphore( 0 )

            newWork = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( 0, 5 ) )
            oldWork = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( 0, 1 ) )

            workqueue.enqueue( newWork )
            workqueue.enqueue( oldWork )

            oldWork.sem.acquire()

            self.assertTrue(  oldWork.fired )
            self.assertFalse( newWork.fired )

            self.assertFalse( oldWork.fail )
            self.assertFalse( newWork.fail )

        finally:
            if workqueue is not None:
                if workqueue.is_alive():
                    workqueue.stop()

                workqueue.join( timeout=5 )


    def test_workUnitInThePast( self ):
        workqueue = None

        try:
            workqueue = workunit.WorkQueue()
            workqueue.start()

            work = LambdaWorkunit( datetime.datetime.now() - datetime.timedelta( 0, 1 ) )
            workqueue.enqueue( work )

            work.sem.acquire()

            self.assertTrue(  work.fired )
            self.assertFalse( work.fail )

        finally:
            if workqueue is not None:
                if workqueue.is_alive():
                    workqueue.stop()

                workqueue.join( timeout=5 )


    def test_stopWithFutureWorkUnit( self ):
        workqueue = None
        try:
            workqueue = workunit.WorkQueue()
            workqueue.start()

            work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( 0, 5 ) )
            workqueue.enqueue( work )
            workqueue.stop()

            self.assertFalse( work.fired )
            self.assertFalse( work.fail  )

        finally:
            if workqueue is not None:
                if workqueue.is_alive():
                    workqueue.stop()

                workqueue.join( timeout=5 )

    def test_stopWithNoWorkUnits( self ):
        workqueue = workunit.WorkQueue()
        workqueue.start()

        time.sleep( 0.5 )

        workqueue.stop()
        workqueue.join( timeout=0.5 )


    def test_preinitialized( self ):
        workqueue = None
        try:
            workqueue = workunit.WorkQueue()

            work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=1 ) )
            workqueue.enqueue( work )

            workqueue.start()
            work.sem.acquire()

            self.assertTrue(  work.fired )
            self.assertFalse( work.fail )

        finally:
            if workqueue is not None:
                if workqueue.is_alive():
                    workqueue.stop()

                workqueue.join( timeout=5 )


    def test_preinitializedPreempted( self ):
        workqueue = None
        try:
            workqueue = workunit.WorkQueue()

            oldWork = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=2 ) )
            workqueue.enqueue( oldWork )
            workqueue.start()

            newWork = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=1 ) )
            workqueue.enqueue( newWork )

            newWork.sem.acquire()
            oldWork.sem.acquire()

            self.assertTrue(  newWork.fired )
            self.assertFalse( newWork.fail )

            self.assertTrue(  oldWork.fired )
            self.assertFalse( oldWork.fail )

        finally:
            if workqueue is not None:
                if workqueue.is_alive():
                    workqueue.stop()

                workqueue.join( timeout=5 )


    # TODO: test where items are appended to the queue before the thread is started

if __name__ == "__main__":
    unittest.main()

