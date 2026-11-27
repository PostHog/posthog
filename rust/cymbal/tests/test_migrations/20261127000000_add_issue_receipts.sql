ALTER TABLE posthog_errortrackingissue
    ADD COLUMN last_received_at TIMESTAMPTZ,
    ADD COLUMN auto_resolved BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN auto_resolve_sync_requested_at TIMESTAMPTZ;

CREATE TABLE posthog_errortrackingsettings (
    team_id INT PRIMARY KEY,
    auto_resolve_after_days INT
);
