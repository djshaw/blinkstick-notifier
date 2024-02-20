import datetime
import threading
import time
import unittest

from myblinkstick import workqueue

class LambdaWorkunit( workqueue.Workunit ):
    def __init__( self, dt, *args, **kwargs ):
        super().__init__( dt, *args, **kwargs )
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
    # When one work unit preempts another, the work queue wakes up and processes the preemtive work
    # unit
    def test_preempt( self ):
        queue = None

        try:
            queue = workqueue.WorkQueue()
            queue.start()

            # Give the queue plenty of time to start, to make sure we exercise the zero length heap
            # condition
            time.sleep( 0.5 )

            new_work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( 0, 5 ) )
            old_work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( 0, 1 ) )

            queue.enqueue( new_work )
            queue.enqueue( old_work )

            old_work.sem.acquire() # pylint: disable=consider-using-with

            self.assertTrue(  old_work.fired )
            self.assertFalse( new_work.fired )

            self.assertFalse( old_work.fail )
            self.assertFalse( new_work.fail )

        finally:
            if queue is not None:
                if queue.is_alive():
                    queue.stop()

                queue.join( timeout=5 )


    def test_work_unit_in_the_past( self ):
        queue = None

        try:
            queue = workqueue.WorkQueue()
            queue.start()

            work = LambdaWorkunit( datetime.datetime.now() - datetime.timedelta( 0, 1 ) )
            queue.enqueue( work )

            work.sem.acquire() # pylint: disable=consider-using-with

            self.assertTrue(  work.fired )
            self.assertFalse( work.fail )

        finally:
            if queue is not None:
                if queue.is_alive():
                    queue.stop()

                queue.join( timeout=5 )


    def test_stop_with_future_work_unit( self ):
        queue = None
        try:
            queue = workqueue.WorkQueue()
            queue.start()

            work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( 0, 5 ) )
            queue.enqueue( work )
            queue.stop()

            self.assertFalse( work.fired )
            self.assertFalse( work.fail  )

        finally:
            if queue is not None:
                if queue.is_alive():
                    queue.stop()

                queue.join( timeout=5 )

    def test_stop_with_no_work_units( self ):
        queue = workqueue.WorkQueue()
        queue.start()

        time.sleep( 0.5 )

        queue.stop()
        queue.join( timeout=0.5 )


    def test_preinitialized( self ):
        queue = None
        try:
            queue = workqueue.WorkQueue()

            work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=1 ) )
            queue.enqueue( work )

            queue.start()
            work.sem.acquire()

            self.assertTrue(  work.fired )
            self.assertFalse( work.fail )

        finally:
            if queue is not None:
                if queue.is_alive():
                    queue.stop()

                queue.join( timeout=5 )


    def test_preinitialized_preempted( self ):
        """ Before the work queue is started, a work unit is enqueued at 2, the queue thread
            is started, then a work unit enqueued at 1 """
        queue = None
        try:
            queue = workqueue.WorkQueue()

            old_work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=2 ) )
            queue.enqueue( old_work )
            queue.start()

            new_work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=1 ) )
            queue.enqueue( new_work )

            new_work.sem.acquire()
            old_work.sem.acquire()

            self.assertTrue(  new_work.fired )
            self.assertFalse( new_work.fail )

            self.assertTrue(  old_work.fired )
            self.assertFalse( old_work.fail )

        finally:
            if queue is not None:
                if queue.is_alive():
                    queue.stop()

                queue.join( timeout=5 )


    def test_all_enqueued_before_start( self ):
        queue = None
        try:
            queue = workqueue.WorkQueue()

            old_work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=1 ) )
            queue.enqueue( old_work )

            new_work = LambdaWorkunit( datetime.datetime.now() + datetime.timedelta( seconds=2 ) )
            queue.enqueue( new_work )

            queue.start()

            old_work.sem.acquire() # pylint: disable=consider-using-with
            new_work.sem.acquire() # pylint: disable=consider-using-with

            self.assertTrue(  old_work.fired )
            self.assertFalse( old_work.fail )

            self.assertTrue(  new_work.fired )
            self.assertFalse( new_work.fail )

        finally:
            if queue is not None:
                if queue.is_alive():
                    queue.stop()

                queue.join( timeout=5 )
