-- Reset transition counters that long-parked jobs have run up.
--
-- transition_count is bookkeeping. The janitor's poison-pill guard keys on janitor_touch_count, and
-- the churn threshold only increments a metric, so nothing reads this column to make a decision and
-- resetting it costs no signal. What it can do is overflow: it is a SMALLINT and the increment is a
-- bare + 1, so past 32767 every dequeue fails and the job stops being able to transition at all.
--
-- A job re-parked on a periodic re-check accrues these without anything being wrong, which is how a
-- healthy long-lived run ends up high enough to look like churn.
--
-- Only matched rows are locked, so the scan does not block unrelated dequeues, but lock_timeout
-- still bounds the wait if a matched row is held by a worker mid-transition.

SET LOCAL lock_timeout = '5s';

UPDATE cyclotron_jobs
SET transition_count = 0
WHERE transition_count > 15000;
