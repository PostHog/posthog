-- Reset the transition counters that months of re-parking have pushed toward the SMALLINT ceiling.
--
-- transition_count is bookkeeping: the janitor's poison-pill guard keys on janitor_touch_count, and
-- nothing reads this column to make a decision. What it can do is overflow. It is a SMALLINT, so
-- past 32767 the increment every dequeue performs fails and the job stops being able to transition
-- at all.
--
-- A wait re-parking every ten minutes spent two transitions per cycle, so a long-lived run accrued
-- roughly 250 a day and the oldest are already past 20000. The hourly re-check this ships with cuts
-- that to about 40 a day, which makes this a one-off catch-up rather than a recurring need.
--
-- Only matched rows are locked, so the scan does not block unrelated dequeues, but lock_timeout
-- still bounds the wait if a matched row is held by a worker mid-transition.

SET LOCAL lock_timeout = '5s';

UPDATE cyclotron_jobs
SET transition_count = 0
WHERE transition_count > 15000;
