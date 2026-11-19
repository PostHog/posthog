-- One row per distinct goal that live conversion watchers pinned, so the subscription matcher can check an
-- event against every pinned goal in memory and look up watchers only when one could match. Millions of
-- watchers share a few hundred goals, so this stays small.
CREATE TABLE IF NOT EXISTS conversion_watcher_goals (
    team_id INT NOT NULL,
    function_id UUID NOT NULL,
    -- md5 of goal::text, so writers that pin the same goal land on the same row.
    goal_hash TEXT NOT NULL,
    goal JSONB NOT NULL,
    -- The latest expiry of any watcher holding this goal, so the row outlives every one of them.
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, function_id, goal_hash)
);

-- Drives the janitor's expiry sweep.
CREATE INDEX IF NOT EXISTS idx_conversion_watcher_goals_expires_at
    ON conversion_watcher_goals (expires_at);

-- A single row: every watcher committed before synced_at has its goal in conversion_watcher_goals. The
-- matcher trusts the goals table only while this is recent, and looks watchers up the old way otherwise.
CREATE TABLE IF NOT EXISTS conversion_watcher_goals_sync (
    id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    synced_at TIMESTAMPTZ NOT NULL
);
