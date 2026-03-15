ALTER TABLE posthog_errortrackingsuppressionrule ADD COLUMN sampling_rate DOUBLE PRECISION NOT NULL DEFAULT 1.0;
