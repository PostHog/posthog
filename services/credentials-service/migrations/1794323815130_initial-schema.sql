-- Up Migration

-- One row per stored credential. Secrets live in integration_secrets, never here.
CREATE TABLE integrations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The int id of the Django row that this row came from. Old int references keep resolving through it.
    legacy_id bigint UNIQUE,
    -- No CHECK on owner_type. Team and user ids are integers and fit owner_id. Organization ids are
    -- UUIDs, so an organization owner needs a column type change first.
    owner_type text NOT NULL,
    owner_id bigint NOT NULL,
    kind text NOT NULL,
    external_id text,
    auth_type text NOT NULL,
    is_source_row boolean NOT NULL DEFAULT false,
    config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config) = 'object'),
    errors text NOT NULL DEFAULT '',
    created_by_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    version integer NOT NULL DEFAULT 1,
    deleted_at timestamptz,
    refresh_due_at timestamptz,
    refresh_state text NOT NULL DEFAULT 'idle' CHECK (refresh_state IN ('idle', 'backoff', 'terminal')),
    refresh_attempts integer NOT NULL DEFAULT 0,
    refresh_last_error text,
    refresh_locked_until timestamptz
);

-- NULL external ids stay distinct, the same as the Django unique constraint.
CREATE UNIQUE INDEX integrations_owner_kind_external_id_live
    ON integrations (owner_type, owner_id, kind, external_id)
    WHERE deleted_at IS NULL;

CREATE INDEX integrations_owner_kind ON integrations (owner_type, owner_id, kind);

CREATE INDEX integrations_kind_external_id ON integrations (kind, external_id);

CREATE INDEX integrations_refresh_due_at
    ON integrations (refresh_due_at)
    WHERE refresh_due_at IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX integrations_deleted_at ON integrations (deleted_at) WHERE deleted_at IS NOT NULL;

CREATE TABLE integration_secrets (
    integration_id uuid PRIMARY KEY REFERENCES integrations (id) ON DELETE CASCADE,
    key_id text NOT NULL,
    wrapped_dek bytea NOT NULL,
    ciphertext bytea NOT NULL,
    nonce bytea NOT NULL,
    enc_version smallint NOT NULL,
    rewrapped_at timestamptz,
    legacy_unreadable_keys text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Daily partitions come from pg_partman, which infra sets up. Until then, rows go to the default partition.
CREATE TABLE audit_log (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    deployment text NOT NULL,
    caller text,
    user_id bigint,
    owner_type text,
    owner_id bigint,
    integration_id uuid,
    kind text,
    operation text NOT NULL,
    fields text[] NOT NULL DEFAULT '{}',
    outcome text NOT NULL,
    request_id text,
    jti text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- A primary key on a partitioned table must contain the partition key.
    PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);

CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;

CREATE TABLE idempotency_keys (
    owner_type text NOT NULL,
    owner_id bigint NOT NULL,
    operation text NOT NULL,
    key text NOT NULL,
    -- A replay with the same key but a different body is a client error, not a replay.
    request_hash bytea NOT NULL,
    integration_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '24 hours',
    PRIMARY KEY (owner_type, owner_id, operation, key)
);

CREATE INDEX idempotency_keys_expires_at ON idempotency_keys (expires_at);

-- Down Migration

DROP TABLE idempotency_keys;
DROP TABLE audit_log;
DROP TABLE integration_secrets;
DROP TABLE integrations;
