-- Add 'canceled' value to JobState enum for jobs that are intentionally skipped
-- (e.g., workflow invocations for disabled/archived workflows)
ALTER TYPE JobState ADD VALUE IF NOT EXISTS 'canceled';
