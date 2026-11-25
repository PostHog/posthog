-- Mirrors error_tracking/0056_errortrackingissue_resolved_at_latest_release, which Django owns.
ALTER TABLE posthog_errortrackingissue ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE posthog_errortrackingissue ADD COLUMN IF NOT EXISTS resolved_until TEXT;
ALTER TABLE posthog_errortrackingissue ADD COLUMN IF NOT EXISTS latest_release_id UUID;
ALTER TABLE posthog_errortrackingissue ADD COLUMN IF NOT EXISTS latest_release_created_at TIMESTAMPTZ;
