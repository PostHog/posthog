-- Per-team counter for fast-class (transactional) email dequeue_seq values.
--
-- Fast and bulk email are compared only within their own priority class, so a
-- separate counter row keeps a team's transactional sends from waiting on the
-- row lock its own broadcast holds in cyclotron_email_team_seq. Rows are
-- seeded lazily from that table's high-water mark for the team, so it starts
-- empty and needs no backfill.
CREATE TABLE IF NOT EXISTS cyclotron_email_team_seq_fast (
    team_id INT PRIMARY KEY,
    counter BIGINT NOT NULL
);
