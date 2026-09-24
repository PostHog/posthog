ALTER TABLE posthog_errortrackingissue
    ADD COLUMN last_received_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN auto_resolve_sync_requested_at TIMESTAMPTZ;
