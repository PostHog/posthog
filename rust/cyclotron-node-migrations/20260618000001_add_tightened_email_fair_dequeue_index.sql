-- no-transaction
--
-- Tightened replacement for idx_cyclotron_jobs_email_fair_dequeue. The new
-- predicate excludes rows with NULL dequeue_seq so future-scheduled and
-- legacy rows don't bloat the index — they're promoted into a seq by the
-- janitor's promoteScheduledEmailJobs pass when their `scheduled` enters
-- the assignment window, at which point they enter this index.
--
-- A new index name is used so the old index can keep serving the
-- fairDequeueJobs query while this one builds. The old index is dropped
-- in the next migration (20260618000002). Splitting DROP + CREATE across
-- two files is required because sqlx's `-- no-transaction` directive
-- only covers a single CONCURRENTLY statement per migration.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_email_fair_dequeue_v2
    ON cyclotron_jobs (dequeue_seq ASC)
    WHERE status = 'available'
      AND queue_name = 'email'
      AND dequeue_seq IS NOT NULL;
