-- Fixup: the first iteration of `agent_session_credential` (in
-- 1780247580000_agent_session_credential.sql) shipped with a plaintext
-- `credentials JSONB` column before we settled on encryption-at-rest.
-- The migration then got edited in place to add encryption — but
-- node-pg-migrate had already marked it applied under the same name,
-- so the column change was never executed against any DB that ran the
-- first version.
--
-- This migration brings any such DB onto the encrypted shape. New DBs
-- skip it (the column it drops won't exist; the column it adds will
-- already be there post-first-migration once that file is itself fixed).
-- Forward-only per agent-migrations convention.

ALTER TABLE agent_session_credential
    DROP COLUMN IF EXISTS credentials;

ALTER TABLE agent_session_credential
    ADD COLUMN IF NOT EXISTS encrypted_credentials TEXT;

-- Backfill: no data should exist (table is transient + per-session),
-- but if any rows are present from the brief plaintext window, mark
-- them expired so the lazy expiry in PgCredentialBroker.resolve clears
-- them on first read.
UPDATE agent_session_credential
   SET expires_at = NOW() - INTERVAL '1 second'
 WHERE encrypted_credentials IS NULL;

ALTER TABLE agent_session_credential
    ALTER COLUMN encrypted_credentials SET NOT NULL;

-- Down migration intentionally omitted — agent-migrations is forward-only.
