-- Add name and description columns to posthog_errortrackingissue
ALTER TABLE posthog_errortrackingissue ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE posthog_errortrackingissue ADD COLUMN IF NOT EXISTS description TEXT;

-- Add first_seen column to posthog_errortrackingissuefingerprintv2
ALTER TABLE posthog_errortrackingissuefingerprintv2 ADD COLUMN IF NOT EXISTS first_seen TIMESTAMPTZ;
