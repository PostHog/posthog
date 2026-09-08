-- Hand-written tables. Tier A ts_*/cur_* tables are created by the sink on demand.

CREATE TABLE IF NOT EXISTS events (
    id         bigserial PRIMARY KEY,
    server_id  text NOT NULL,
    instance   text NOT NULL DEFAULT 'writer',
    datname    text,
    at         timestamptz NOT NULL,
    kind       text NOT NULL,          -- stats_reset | pgss_dealloc | schema_change | setting_change | ...
    subject    text NOT NULL,
    before     jsonb,
    after      jsonb
);
CREATE INDEX IF NOT EXISTS events_server_at ON events (server_id, at DESC);

CREATE TABLE IF NOT EXISTS collector_runs (
    collector   text NOT NULL,
    server_id   text NOT NULL,
    instance    text NOT NULL DEFAULT 'writer',
    datname     text,
    started_at  timestamptz NOT NULL,
    duration_ms bigint NOT NULL,
    rows        bigint NOT NULL,
    error       text
);
CREATE INDEX IF NOT EXISTS collector_runs_at ON collector_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS collector_state (
    collector  text NOT NULL,
    server_id  text NOT NULL,
    instance   text NOT NULL DEFAULT 'writer',
    datname    text NOT NULL DEFAULT '',
    state      jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (collector, server_id, instance, datname)
);

CREATE TABLE IF NOT EXISTS cur_servers (
    server_id         text PRIMARY KEY,
    system_identifier bigint,
    version_num       int,
    version           text,
    aurora_version    text,
    instances         text[] NOT NULL DEFAULT '{}',
    databases         text[] NOT NULL DEFAULT '{}',
    first_seen        timestamptz NOT NULL,
    last_seen         timestamptz NOT NULL
);
