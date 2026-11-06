ALTER TABLE cyclotron_email_attachments
    ADD COLUMN IF NOT EXISTS storage_key TEXT,
    ALTER COLUMN content DROP NOT NULL;
