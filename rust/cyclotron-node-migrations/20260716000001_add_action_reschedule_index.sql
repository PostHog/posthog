-- no-transaction
--
-- Supports the timing-edit reschedule sweep (CyclotronV2Manager.rescheduleParkedJobs),
-- whose queries filter parked rows by
--   function_id = $1 AND action_id = ANY($2) AND status = 'available' AND scheduled > $3
-- (team_id is also in the predicate, but function_id — a per-workflow UUID — is already
-- maximally selective, so team_id is left to a residual filter over the tiny result).
--
-- Without this, the planner narrows via idx_cyclotron_jobs_function_id and heap-filters
-- action_id/status/scheduled. The email fair-dequeue composite migration (20260622000001)
-- measured that fallback at ~4x buffer reads / ~10x execution time; the sweep repeats the
-- predicate up to maxChunksPerCall + 2 times per call against workflows with parked
-- backlogs in the hundreds of thousands, on the same table the workers dequeue from.
-- `scheduled` as a trailing key column makes the sweep's `scheduled > $x` an Index Cond
-- (walked-past rows eliminated in-index), for the same reason as 20260622000001.
--
-- Partial on status = 'available': only parked rows are sweepable, and it keeps the
-- index off the write path of every terminal-state transition.
--
-- Recovery note: if this CONCURRENTLY build is ever interrupted, it leaves the index
-- INVALID and a rerun's IF NOT EXISTS will NOT rebuild it. A drop-first statement can't
-- fix that here - sqlx runs a no-transaction migration as one implicitly-transactional
-- batch, so CONCURRENTLY statements must be alone in their file, and a separate drop
-- migration wouldn't re-run on retry. Recover manually:
--   DROP INDEX CONCURRENTLY idx_cyclotron_jobs_action_reschedule;  -- then re-run migrations
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_action_reschedule
    ON cyclotron_jobs (function_id, action_id, scheduled)
    WHERE status = 'available';
