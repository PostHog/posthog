// Schema for the agent-memory dev slice.
//
// One store per team (rows scoped by team_id — the hard tenancy boundary).
// Access is per-pattern via agent_memory_pattern_grant. "Private" is the
// degenerate case: a pattern granted only to its creating application.
//
// Storage is a deliberate slice simplification vs the plan's full design:
// entries are JSONB rows, not per-pattern real tables. It exercises the whole
// surface (patterns / entries / facets / links / allowlist / prime) without
// dynamic DDL. The production service graduates to real tables.

import type { Pool } from 'pg'

export const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS agent_memory_pattern (
    team_id        INT  NOT NULL,
    name           TEXT NOT NULL,
    doctrine       TEXT NOT NULL DEFAULT '',
    -- [{ name, type }] — slice keeps all facets text; used to build recall text.
    facets         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by     TEXT,                -- application id/slug that created it
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at    TIMESTAMPTZ,
    PRIMARY KEY (team_id, name)
);

-- Per-pattern allowlist. The single access mechanism (§3 of the plan).
CREATE TABLE IF NOT EXISTS agent_memory_pattern_grant (
    team_id        INT  NOT NULL,
    pattern        TEXT NOT NULL,
    application_id TEXT NOT NULL,
    access         TEXT NOT NULL CHECK (access IN ('read', 'write')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, pattern, application_id)
);

CREATE TABLE IF NOT EXISTS agent_memory_entry (
    id             BIGSERIAL PRIMARY KEY,
    team_id        INT  NOT NULL,
    pattern        TEXT NOT NULL,
    facets         JSONB NOT NULL DEFAULT '{}'::jsonb,
    version        INT  NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS agent_memory_entry_scope_idx
    ON agent_memory_entry (team_id, pattern) WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS agent_memory_link (
    id             BIGSERIAL PRIMARY KEY,
    team_id        INT  NOT NULL,
    source_pattern TEXT NOT NULL,
    source_id      BIGINT NOT NULL,
    target_pattern TEXT NOT NULL,
    target_id      BIGINT NOT NULL,
    label          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS agent_memory_link_src_idx
    ON agent_memory_link (team_id, source_pattern, source_id) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS agent_memory_link_tgt_idx
    ON agent_memory_link (team_id, target_pattern, target_id) WHERE archived_at IS NULL;
`

export const DROP_SQL = `
DROP TABLE IF EXISTS agent_memory_link CASCADE;
DROP TABLE IF EXISTS agent_memory_entry CASCADE;
DROP TABLE IF EXISTS agent_memory_pattern_grant CASCADE;
DROP TABLE IF EXISTS agent_memory_pattern CASCADE;
`

export async function applySchema(pool: Pool): Promise<void> {
    await pool.query(SCHEMA_SQL)
}

export async function dropSchema(pool: Pool): Promise<void> {
    await pool.query(DROP_SQL)
}
