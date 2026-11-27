ALTER TABLE posthog_errortrackingissue
    ADD COLUMN last_received_at TIMESTAMPTZ;

CREATE TABLE posthog_errortrackingsettings (
    team_id INT PRIMARY KEY,
    auto_resolve_after_days INT
);
