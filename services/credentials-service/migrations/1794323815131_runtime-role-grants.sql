-- Up Migration

-- One row per accepted token id, so a stolen token cannot be replayed. Rows are deleted lazily after expiry.
CREATE TABLE auth_jti (
    deployment text NOT NULL,
    jti text NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (deployment, jti)
);

CREATE INDEX auth_jti_expires_at ON auth_jti (expires_at);

-- The migrate role owns every table. The runtime role gets only what the service needs.
-- The role name comes from the session setting credentials_service.runtime_role, which the migrate
-- entry point sets from CREDENTIALS_SERVICE_RUNTIME_ROLE. When it is empty (single-role local
-- development), no grants are made.
-- Every later migration that adds a table must grant on it in the same way.
DO $$
DECLARE
    runtime_role text := nullif(current_setting('credentials_service.runtime_role', true), '');
BEGIN
    IF runtime_role IS NULL THEN
        RAISE NOTICE 'credentials_service.runtime_role is not set: skipping grants';
        RETURN;
    END IF;

    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON integrations, integration_secrets, idempotency_keys, auth_jti TO %I',
        runtime_role
    );
    -- Append-only: no UPDATE, DELETE or TRUNCATE. The runtime role does not own the table.
    EXECUTE format('GRANT SELECT, INSERT ON audit_log TO %I', runtime_role);
END
$$;

-- Down Migration

DROP TABLE auth_jti;
