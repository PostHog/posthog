-- no-transaction
-- The scheduled sends API lists a team's email jobs that no worker has claimed, and a gauge counts them across
-- teams. The email queue holds every queued send, so a partial index keeps both reads to the waiting rows.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_unclaimed
    ON cyclotron_jobs (team_id, scheduled, id)
    WHERE queue_name = 'email' AND status = 'available' AND transition_count = 0;
