-- updates to the posthog_errortrackingissue table that never made it into posthog/rust test migrations
ALTER TABLE posthog_errortrackingissue ADD COLUMN name text;

ALTER TABLE posthog_errortrackingissue ADD COLUMN description text;

