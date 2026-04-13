-- Stores the matched event data (name + properties) when the consumer wakes a job.
-- The handler reads this to log which event matched and to output it as a workflow variable.
ALTER TABLE cyclotron_event_subscriptions ADD COLUMN matched_event JSONB;
