-- Cancellation request marker, distinct from status='canceled': producers set it on
-- in-flight jobs, and the owning worker performs the actual cancellation (terminal
-- status flip plus lifecycle/metric writes) when it next observes the job.
ALTER TABLE cyclotron_jobs ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ;
