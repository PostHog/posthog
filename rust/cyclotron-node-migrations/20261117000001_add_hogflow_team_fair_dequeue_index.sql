-- no-transaction
-- The hogflow team-fair dequeue walks the lanes of the queue, one team at one priority, and reads the
-- oldest due rows of each lane. Leading on (priority, team_id) gives one index seek per lane, and
-- `scheduled` as the trailing key keeps `scheduled <= NOW()` an index condition. The worker reads this
-- index only while CDP_CYCLOTRON_HOGFLOW_TEAM_FAIR_DEQUEUE is on.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cyclotron_jobs_hogflow_team_fair_dequeue
    ON cyclotron_jobs (priority, team_id, scheduled)
    WHERE status = 'available' AND queue_name = 'hogflow';
