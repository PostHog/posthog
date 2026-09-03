-- Cancellation request marker, distinct from status='canceled': producers set it on
-- in-flight jobs, and the owning worker performs the actual cancellation (terminal
-- status flip plus lifecycle/metric writes) when it next observes the job.
--
-- ADD COLUMN with no default is metadata-only, but it still takes a brief
-- ACCESS EXCLUSIVE lock on a hot table: queueing for it behind a long-running
-- query parks everything else behind us. lock_timeout bounds that wait; on
-- timeout the per-file transaction aborts, nothing is recorded, and the next
-- migration run retries this idempotent file.

SET LOCAL lock_timeout = '5s';

ALTER TABLE cyclotron_jobs ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ;
