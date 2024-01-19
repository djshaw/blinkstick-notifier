workunit
========

A scheduler that can be immediate interrupted to run a job.

A schedule is represented as `WorkQueue`.  A job is a `Workunit`.  When a
`WorkQueue` is instantiated, a non-daemon thread is started to execute jobs.
Only one work unit is executed at a time.  Jobs are added to the queue with
`enqueue()`. When a job is added to the queue, if the thread is idle, and if
the job can be executed immediately, the idle execution thread is immediately
woken up to execute the job.

When a work unit finishes executing, the thread will sleep until the next work
unit is scheduled to be executed.  The implementation assumes that it will
sleep for the exact amount of time it says to sleep for.  This assumption is
not always valid.

To stop the queue, invoke `stop()`.  If the thread isn't executing any work
units, the thread will immediately stop.  If a work unit is being executed, the
thread will be stopped immediately after the current work unit is done.

