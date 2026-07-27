-- Fair dequeue for the email queue, scoped to queue_name='email'.
--
-- `dequeue_seq` is a precomputed sort key assigned at insert time so the
-- email worker's dequeue ORDER BY stays cheap (no window functions, no
-- recursive CTEs). It interleaves jobs across tenants: each tenant's first
-- job sorts together, then each tenant's second job, etc. A new tenant's
-- single email no longer waits behind another tenant's 2M-email campaign.
--
-- The column is NULL for non-email jobs — completely transparent to the
-- hog/hogflow worker paths.
ALTER TABLE cyclotron_jobs
    ADD COLUMN IF NOT EXISTS dequeue_seq BIGINT;

-- Per-team monotonic counter, used to compute dequeue_seq at insert time:
--     dequeue_seq = counter × 16,777,216 + team_id
--
-- One row per team that has ever sent an email. BIGINT gives ~5 × 10^11
-- jobs per team of headroom before sort_number overflow at the chosen
-- block size (decades at any realistic email volume).
CREATE TABLE IF NOT EXISTS cyclotron_email_team_seq (
    team_id INT PRIMARY KEY,
    counter BIGINT NOT NULL
);
