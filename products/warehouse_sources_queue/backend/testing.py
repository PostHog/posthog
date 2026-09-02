"""Shared test helpers for suites that exercise the queue tables.

Tests run against the default Django test database, not the dedicated queue
database: the product migration only applies to the real queue DB, so suites
create the tables here with DDL that mirrors ``migrations/``. Keep the two in
sync when the schema changes.
"""

from typing import Any

from django.db import connection

import psycopg

from products.warehouse_sources_queue.backend.core.generic_jobs import JOB_LEASE_TABLE, JOB_STATUS_TABLE, JOB_TABLE
from products.warehouse_sources_queue.backend.core.jobs_db import (
    BATCH_TABLE,
    LEASE_TABLE,
    STATUS_TABLE,
    STATUS_VIEW,
    BatchQueue,
)


def get_test_database_url() -> str:
    s = connection.settings_dict
    host = s.get("HOST", "localhost") or "localhost"
    port = s.get("PORT", "5432") or "5432"
    return f"postgres://{s['USER']}:{s['PASSWORD']}@{host}:{port}/{s['NAME']}"


def ensure_queue_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {BATCH_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            source_id VARCHAR(200) NOT NULL,
            job_id VARCHAR(200) NOT NULL,
            run_uuid VARCHAR(200) NOT NULL,
            batch_index INT NOT NULL,
            s3_path TEXT NOT NULL,
            row_count INT NOT NULL,
            byte_size BIGINT NOT NULL,
            is_final_batch BOOLEAN NOT NULL,
            total_batches INT,
            total_rows BIGINT,
            sync_type VARCHAR(32) NOT NULL,
            cumulative_row_count BIGINT NOT NULL DEFAULT 0,
            resource_name VARCHAR(400) NOT NULL,
            is_resume BOOLEAN NOT NULL DEFAULT FALSE,
            is_first_ever_sync BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            latest_attempt SMALLINT NOT NULL DEFAULT 0,
            state_changed_at TIMESTAMPTZ,
            superseded BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Self-heal pre-existing test DBs where CREATE TABLE IF NOT EXISTS is a no-op.
    conn.execute(f"""
        ALTER TABLE {BATCH_TABLE}
            ADD COLUMN IF NOT EXISTS latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS latest_attempt SMALLINT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS state_changed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS superseded BOOLEAN NOT NULL DEFAULT FALSE
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_claimable_idx ON {BATCH_TABLE} (team_id, created_at, batch_index)
            WHERE latest_state IN ('pending', 'waiting_retry')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_run_gate_idx ON {BATCH_TABLE} (run_uuid, latest_state, batch_index)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_schema_busy_idx ON {BATCH_TABLE} (team_id, schema_id)
            WHERE latest_state = 'executing'
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_failed_changed_idx ON {BATCH_TABLE} (state_changed_at)
            WHERE latest_state = 'failed'
    """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS sb_job_id_idx ON {BATCH_TABLE} (job_id)")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {STATUS_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES {BATCH_TABLE}(id) ON DELETE CASCADE,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sbs_batch_id_desc_state_idx
            ON {STATUS_TABLE} (batch_id, created_at DESC, id DESC, job_state)
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {LEASE_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sgl_team_schema_uniq UNIQUE (team_id, schema_id)
        )
    """)
    conn.execute(f"DROP VIEW IF EXISTS {STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)


def truncate_queue_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"TRUNCATE {STATUS_TABLE}, {BATCH_TABLE}, {LEASE_TABLE} RESTART IDENTITY CASCADE")


BATCH_DEFAULTS: dict[str, Any] = {
    "team_id": 1,
    "schema_id": "schema-1",
    "source_id": "source-1",
    "job_id": "job-1",
    "run_uuid": "run-1",
    "batch_index": 0,
    "s3_path": "s3://bucket/path",
    "row_count": 100,
    "byte_size": 1024,
    "is_final_batch": False,
    "total_batches": None,
    "total_rows": None,
    "sync_type": "full_refresh",
    "cumulative_row_count": 0,
    "resource_name": "test_resource",
    "is_resume": False,
    "is_first_ever_sync": False,
    "metadata": {},
}


async def insert_batch(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str:
    params = {**BATCH_DEFAULTS, **overrides}
    return await BatchQueue.insert(conn, **params)


def ensure_generic_job_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {JOB_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            kind VARCHAR(100) NOT NULL,
            lane VARCHAR(16) NOT NULL,
            group_key VARCHAR(400) NOT NULL,
            team_id BIGINT NOT NULL,
            run_id VARCHAR(200),
            sequence INT NOT NULL DEFAULT 0,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            priority SMALLINT NOT NULL DEFAULT 0,
            dedup_key VARCHAR(400),
            latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            latest_attempt SMALLINT NOT NULL DEFAULT 0,
            state_changed_at TIMESTAMPTZ,
            superseded BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_claimable_idx ON {JOB_TABLE} (lane, kind, team_id, created_at, sequence)
            WHERE latest_state IN ('pending', 'waiting_retry')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_run_gate_idx ON {JOB_TABLE} (run_id, latest_state, sequence)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_group_busy_idx ON {JOB_TABLE} (lane, group_key)
            WHERE latest_state = 'executing'
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS qj_dedup_idx ON {JOB_TABLE} (kind, dedup_key)
            WHERE dedup_key IS NOT NULL
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {JOB_STATUS_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {JOB_LEASE_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            lane VARCHAR(16) NOT NULL,
            group_key VARCHAR(400) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT qjl_lane_group_uniq UNIQUE (lane, group_key)
        )
    """)


def truncate_generic_job_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"TRUNCATE {JOB_STATUS_TABLE}, {JOB_TABLE}, {JOB_LEASE_TABLE} RESTART IDENTITY CASCADE")


JOB_DEFAULTS: dict[str, Any] = {
    "kind": "test.kind",
    "lane": "test",
    "group_key": "1:group-1",
    "team_id": 1,
    "payload": {},
}
