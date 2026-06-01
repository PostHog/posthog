-- Per-session credential broker store. Backs `CredentialBroker` for the
-- v0 multi-mode auth design (per the agent-concierge plan).
--
-- Deliberately separate from `agent_session`: principals (identity) stay
-- on the session row and are durable; credentials (tokens) live here,
-- are transient, TTL'd, and never participate in the principal-match
-- machinery. Cleared explicitly at session end + by an `expires_at`
-- sweep the janitor runs.
--
-- **Encrypted at rest**. The `encrypted_credentials` column holds
-- Fernet-encrypted ciphertext produced by `EncryptedFields` (same
-- mechanism as `AgentApplication.encrypted_env`). The on-disk row is
-- opaque; only a process with the matching `ENCRYPTION_SALT_KEYS` env
-- can decrypt. Rotating keys works through `EncryptedFields`'
-- try-each-in-order decrypt path.
--
-- One row per (session_id). Overwriting (e.g. /send refreshes a rotated
-- OAuth token) is a plain UPSERT.

CREATE TABLE IF NOT EXISTS agent_session_credential (
    session_id              UUID PRIMARY KEY,
    encrypted_credentials   TEXT NOT NULL,
    expires_at              TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_session_credential_expires_at_idx
    ON agent_session_credential (expires_at);

-- Down migration intentionally omitted — agent-migrations is forward-only.
