-- Add type column to distinguish wait_step vs conversion subscriptions.
ALTER TABLE cyclotron_event_subscriptions ADD COLUMN type TEXT NOT NULL DEFAULT 'wait_step';
