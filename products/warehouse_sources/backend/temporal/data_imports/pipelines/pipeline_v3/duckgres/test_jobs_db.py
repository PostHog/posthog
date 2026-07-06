from typing import Any

import pytest

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import (
    DUCKGRES_APPLY_TABLE,
    DUCKGRES_STATUS_TABLE,
    DUCKGRES_STATUS_VIEW,
    DuckgresBatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    LEASE_TABLE,
    STATUS_TABLE,
    STATUS_VIEW,
    BatchQueue,
)


def _get_test_database_url() -> str:
    from django.db import connection

    settings = connection.settings_dict
    host = settings.get("HOST", "localhost") or "localhost"
    port = settings.get("PORT", "5432") or "5432"
    return f"postgres://{settings['USER']}:{settings['PASSWORD']}@{host}:{port}/{settings['NAME']}"


def _ensure_tables(conn: psycopg.Connection[Any]) -> None:
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
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
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
        CREATE TABLE IF NOT EXISTS {DUCKGRES_STATUS_TABLE} (
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
        CREATE TABLE IF NOT EXISTS {DUCKGRES_APPLY_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            run_uuid VARCHAR(200) NOT NULL,
            batch_index INT NOT NULL,
            batch_id UUID NOT NULL REFERENCES {BATCH_TABLE}(id) ON DELETE CASCADE,
            row_count INT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sbdga_unique_batch_apply UNIQUE (team_id, schema_id, run_uuid, batch_index)
        )
    """)
    conn.execute(f"DROP VIEW IF EXISTS {STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)
    conn.execute(f"DROP VIEW IF EXISTS {DUCKGRES_STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {DUCKGRES_STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {DUCKGRES_STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)
    # Needed so the Delta queue's claim CTE (referenced by the contract test below) can plan.
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


def _truncate_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        f"TRUNCATE {DUCKGRES_APPLY_TABLE}, {DUCKGRES_STATUS_TABLE}, {STATUS_TABLE}, {BATCH_TABLE}, {LEASE_TABLE} RESTART IDENTITY CASCADE"
    )


_BATCH_DEFAULTS: dict[str, Any] = {
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


async def _insert_batch(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str:
    return await BatchQueue.insert(conn, **{**_BATCH_DEFAULTS, **overrides})


@pytest.fixture(scope="session")
def _db_url() -> str:
    return _get_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def _create_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        _ensure_tables(conn)


@pytest.fixture(autouse=True)
def _clean_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        _truncate_tables(conn)
        conn.execute("SELECT pg_advisory_unlock_all()")


@pytest.fixture
async def conn(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.mark.django_db(transaction=True)
class TestDuckgresBatchQueueEligibility:
    @pytest.mark.asyncio
    async def test_ignores_batches_until_delta_succeeds(self, conn):
        await _insert_batch(conn)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert batches == []

    @pytest.mark.asyncio
    async def test_returns_delta_succeeded_batches(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert len(batches) == 1
        assert str(batches[0].id) == batch_id

    @pytest.mark.asyncio
    async def test_skips_duckgres_succeeded_batches(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)
        await DuckgresBatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert batches == []

    @pytest.mark.asyncio
    async def test_returns_duckgres_retry_batches(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)
        await DuckgresBatchQueue.update_status(conn, batch_id=batch_id, job_state="waiting_retry", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert len(batches) == 1
        assert batches[0].latest_attempt == 1

    @pytest.mark.asyncio
    async def test_enforces_prior_batch_apply_order(self, conn):
        first_id = await _insert_batch(conn, batch_index=0)
        second_id = await _insert_batch(conn, batch_index=1)
        await BatchQueue.update_status(conn, batch_id=first_id, job_state="succeeded", attempt=1)
        await BatchQueue.update_status(conn, batch_id=second_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert [batch.batch_index for batch in batches] == [0]

    @pytest.mark.asyncio
    async def test_final_marker_waits_for_matching_data_batch_apply(self, conn):
        data_id = await _insert_batch(conn, batch_index=0, is_final_batch=False)
        final_id = await _insert_batch(conn, batch_index=0, is_final_batch=True, total_batches=1, total_rows=100)
        await BatchQueue.update_status(conn, batch_id=data_id, job_state="succeeded", attempt=1)
        await BatchQueue.update_status(conn, batch_id=final_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [str(batch.id) for batch in batches] == [data_id]

        await DuckgresBatchQueue.mark_applied(conn, batch=batches[0])
        await DuckgresBatchQueue.unlock_for_batches(conn, batches=batches)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [str(batch.id) for batch in batches] == [final_id]

    @pytest.mark.asyncio
    async def test_delta_failed_run_is_skipped(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)
        failed_id = await _insert_batch(conn, batch_index=1)
        await BatchQueue.update_status(conn, batch_id=failed_id, job_state="failed", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert batches == []

    @pytest.mark.asyncio
    async def test_duckgres_failed_run_is_skipped(self, conn):
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)
        failed_id = await _insert_batch(conn, batch_index=1)
        await BatchQueue.update_status(conn, batch_id=failed_id, job_state="succeeded", attempt=1)
        await DuckgresBatchQueue.update_status(conn, batch_id=failed_id, job_state="failed", attempt=3)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert batches == []


async def _mark_applied_raw(
    conn: psycopg.AsyncConnection[Any],
    *,
    batch_id: str,
    run_uuid: str,
    batch_index: int,
    team_id: int = 1,
    schema_id: str = "schema-1",
) -> None:
    await conn.execute(
        f"""
        INSERT INTO {DUCKGRES_APPLY_TABLE} (team_id, schema_id, run_uuid, batch_index, batch_id, row_count)
        VALUES (%s, %s, %s, %s, %s, 0)
        """,
        [team_id, schema_id, run_uuid, batch_index, batch_id],
    )


@pytest.mark.django_db(transaction=True)
class TestDuckgresCrossRunOrdering:
    @pytest.mark.asyncio
    async def test_newer_run_blocked_while_older_run_incomplete(self, conn):
        # run-1: batch 0 applied, batch 1 delta-succeeded but unapplied -> incomplete
        old0 = await _insert_batch(conn, run_uuid="run-1", batch_index=0)
        old1 = await _insert_batch(conn, run_uuid="run-1", batch_index=1)
        await BatchQueue.update_status(conn, batch_id=old0, job_state="succeeded", attempt=1)
        await BatchQueue.update_status(conn, batch_id=old1, job_state="succeeded", attempt=1)
        await _mark_applied_raw(conn, batch_id=old0, run_uuid="run-1", batch_index=0)

        # run-2 (newer, same schema): batch 0 delta-succeeded
        new0 = await _insert_batch(conn, run_uuid="run-2", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=new0, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        # Only the older run's next batch is eligible; run-2 waits behind it.
        assert [(b.run_uuid, b.batch_index) for b in batches] == [("run-1", 1)]

    @pytest.mark.asyncio
    async def test_newer_run_eligible_once_older_run_failed(self, conn):
        old0 = await _insert_batch(conn, run_uuid="run-1", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=old0, job_state="succeeded", attempt=1)
        await DuckgresBatchQueue.update_status(conn, batch_id=old0, job_state="failed", attempt=3)

        new0 = await _insert_batch(conn, run_uuid="run-2", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=new0, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)

        assert [(b.run_uuid, b.batch_index) for b in batches] == [("run-2", 0)]

    @pytest.mark.asyncio
    async def test_supersede_retires_older_run_when_replace_head_pending(self, conn):
        # run-1: batch 0 applied, batch 1 delta-succeeded but unapplied
        old0 = await _insert_batch(conn, run_uuid="run-1", batch_index=0)
        old1 = await _insert_batch(conn, run_uuid="run-1", batch_index=1)
        await BatchQueue.update_status(conn, batch_id=old0, job_state="succeeded", attempt=1)
        await BatchQueue.update_status(conn, batch_id=old1, job_state="succeeded", attempt=1)
        await _mark_applied_raw(conn, batch_id=old0, run_uuid="run-1", batch_index=0)

        # run-2: a full_refresh replace head (batch 0) is delta-succeeded
        new0 = await _insert_batch(conn, run_uuid="run-2", batch_index=0, sync_type="full_refresh")
        await BatchQueue.update_status(conn, batch_id=new0, job_state="succeeded", attempt=1)

        superseded = await DuckgresBatchQueue.supersede_replaced_runs(conn)
        assert superseded == 1  # run-1's pending batch 1

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [(b.run_uuid, b.batch_index) for b in batches] == [("run-2", 0)]

    @pytest.mark.asyncio
    async def test_supersede_does_not_touch_incremental_successor(self, conn):
        old0 = await _insert_batch(conn, run_uuid="run-1", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=old0, job_state="succeeded", attempt=1)

        # Newer incremental (not first-ever) run does not replace the table, so the
        # older run's work must still apply first.
        new0 = await _insert_batch(conn, run_uuid="run-2", batch_index=0, sync_type="incremental")
        await BatchQueue.update_status(conn, batch_id=new0, job_state="succeeded", attempt=1)

        superseded = await DuckgresBatchQueue.supersede_replaced_runs(conn)
        assert superseded == 0

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [(b.run_uuid, b.batch_index) for b in batches] == [("run-1", 0)]


@pytest.mark.django_db(transaction=True)
class TestDuckgresTeamFilterAndBacklog:
    @pytest.mark.asyncio
    async def test_team_filter(self, conn):
        batch_id = await _insert_batch(conn, team_id=1)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        # Advisory locks are session-reentrant, so repeated fetches on one conn are fine.
        assert await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, team_ids=[2]) == []
        assert len(await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, team_ids=[1, 2])) == 1
        assert len(await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, team_ids=None)) == 1

    @pytest.mark.asyncio
    async def test_backlog_stats(self, conn):
        batch_id = await _insert_batch(conn, sync_type="incremental")
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        count, oldest_age, blocked, blocked_age = await DuckgresBatchQueue.get_backlog_stats(conn)
        assert (count, blocked) == (1, 0)
        assert oldest_age is not None and oldest_age >= 0
        assert blocked_age is None

        # The same batch counts as blocked (not eligible) once its schema is gated.
        count, oldest_age, blocked, blocked_age = await DuckgresBatchQueue.get_backlog_stats(
            conn, blocked_schema_ids=["schema-1"]
        )
        assert (count, blocked) == (0, 1)
        assert oldest_age is None and blocked_age is not None

        # The v3 allow-list scopes the gauges too: a non-eligible schema drops
        # out of both the eligible and blocked counts.
        count, oldest_age, blocked, blocked_age = await DuckgresBatchQueue.get_backlog_stats(
            conn, eligible_schema_ids=["other-schema"]
        )
        assert (count, blocked) == (0, 0)

        await _mark_applied_raw(conn, batch_id=batch_id, run_uuid="run-1", batch_index=0)
        count, oldest_age, blocked, blocked_age = await DuckgresBatchQueue.get_backlog_stats(conn)
        assert (count, blocked) == (0, 0)
        assert oldest_age is None and blocked_age is None


@pytest.mark.django_db(transaction=True)
class TestBackfillGating:
    @pytest.mark.asyncio
    async def test_blocked_schema_live_batches_are_excluded(self, conn):
        batch_id = await _insert_batch(conn, sync_type="incremental")
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        assert await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, blocked_schema_ids=["schema-1"]) == []
        assert len(await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, blocked_schema_ids=["other"])) == 1

    @pytest.mark.asyncio
    async def test_backfill_batches_pass_the_block(self, conn):
        batch_id = await _insert_batch(
            conn,
            run_uuid="duckgres-backfill-schema-1-v7",
            job_id="duckgres-backfill",
            is_resume=True,
            metadata={"duckgres_backfill": True, "chunk_paths": ["s3://b/c0.parquet"], "chunk_count": 1},
        )
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, blocked_schema_ids=["schema-1"])

        assert [b.run_uuid for b in batches] == ["duckgres-backfill-schema-1-v7"]

    @pytest.mark.asyncio
    async def test_backfill_run_never_plans_as_replace_head(self, conn):
        # is_resume=True keeps the synthetic full_refresh run out of supersede's
        # replace-head set: a backfill must never retire other runs.
        batch_id = await _insert_batch(
            conn,
            run_uuid="duckgres-backfill-schema-1-v7",
            job_id="duckgres-backfill",
            is_resume=True,
            metadata={"duckgres_backfill": True},
        )
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        old = await _insert_batch(conn, run_uuid="run-0", sync_type="incremental")
        await BatchQueue.update_status(conn, batch_id=old, job_state="succeeded", attempt=1)

        assert await DuckgresBatchQueue.supersede_replaced_runs(conn) == 0


@pytest.mark.django_db(transaction=True)
class TestBackfillQueueContracts:
    @pytest.mark.asyncio
    async def test_pre_succeeded_synthetic_rows_invisible_to_delta_fetch(self, conn):
        """The load-bearing trick: backfill rows must never be claimed by the
        Delta consumer (it would load them into the Delta table) while being
        immediately eligible for the duckgres fetch."""
        batch_id = await _insert_batch(
            conn,
            run_uuid="duckgres-backfill-schema-1-v1-gdeadbeef",
            job_id="duckgres-backfill",
            is_resume=True,
            metadata={"duckgres_backfill": True, "chunk_paths": ["s3://b/c0.parquet"], "chunk_count": 1},
        )
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        assert await BatchQueue.get_unprocessed_and_lock(conn, owner_token="test-owner") == []

        duck = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [str(b.id) for b in duck] == [batch_id]

    @pytest.mark.asyncio
    async def test_backfill_chunks_ignore_older_live_runs(self, conn):
        """The cross-run gate exempts backfill chunks from waiting on live
        runs: pre-snapshot runs are retired separately, and post-snapshot
        runs must apply AFTER the swap — neither may deadlock the backfill."""
        live = await _insert_batch(conn, run_uuid="run-old", sync_type="incremental")
        await BatchQueue.update_status(conn, batch_id=live, job_state="succeeded", attempt=1)

        chunk = await _insert_batch(
            conn,
            run_uuid="duckgres-backfill-schema-1-v1-gcafe0000",
            job_id="duckgres-backfill",
            is_resume=True,
            metadata={"duckgres_backfill": True, "chunk_paths": ["s3://b/c0.parquet"], "chunk_count": 1},
        )
        await BatchQueue.update_status(conn, batch_id=chunk, job_state="succeeded", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, blocked_schema_ids=["schema-1"])
        assert [str(b.id) for b in batches] == [chunk]

    @pytest.mark.asyncio
    async def test_live_batches_still_queue_behind_backfill_run(self, conn):
        chunk = await _insert_batch(
            conn,
            run_uuid="duckgres-backfill-schema-1-v1-gcafe0000",
            job_id="duckgres-backfill",
            is_resume=True,
            metadata={"duckgres_backfill": True, "chunk_paths": ["s3://b/c0.parquet"], "chunk_count": 1},
        )
        await BatchQueue.update_status(conn, batch_id=chunk, job_state="succeeded", attempt=1)

        live = await _insert_batch(conn, run_uuid="run-new")
        await BatchQueue.update_status(conn, batch_id=live, job_state="succeeded", attempt=1)

        # Schema primed (not blocked) but the backfill run is older and
        # incomplete: the live batch must wait.
        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [str(b.id) for b in batches] == [chunk]

    @pytest.mark.asyncio
    async def test_preapply_covered_batches_uses_snapshot_commit_keys(self, conn, _db_url):
        """Batches committed into the pinned Delta snapshot get pre-applied
        regardless of queue timing; siblings absent from the snapshot key set
        survive, stay eligible, and their run is never poisoned."""
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres import (
            backfill_queue,
        )

        covered_a = await _insert_batch(conn, run_uuid="run-straddling", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=covered_a, job_state="succeeded", attempt=1)
        late_b = await _insert_batch(conn, run_uuid="run-straddling", batch_index=1)
        await BatchQueue.update_status(conn, batch_id=late_b, job_state="succeeded", attempt=1)

        with psycopg.Connection.connect(_db_url, autocommit=True) as sync_conn:
            preapplied = backfill_queue.preapply_covered_batches(
                sync_conn,
                team_id=1,
                schema_id="schema-1",
                covered_batches=[("run-straddling", 0)],
                reason="covered v1",
            )
            preapplied_again = backfill_queue.preapply_covered_batches(
                sync_conn,
                team_id=1,
                schema_id="schema-1",
                covered_batches=[("run-straddling", 0)],
                reason="covered v1",
            )

        assert preapplied == 1  # covered_a only
        assert preapplied_again == 0  # idempotent; late_b is absent from the snapshot key set

        # The straddling sibling is NOT lost: its head-of-line prev is satisfied
        # by the pre-apply marker, the run is not failed, and it remains the
        # schema's claimable work (post-swap it applies as a live batch).
        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn)
        assert [str(b.id) for b in batches] == [late_b]

    @pytest.mark.asyncio
    async def test_replace_head_runs_bypass_the_blocked_gate(self, conn):
        """A full-refresh replace run rebuilds the table from scratch, so it is
        safe (and required — it is the NEEDS_RESYNC healing path) even while
        the schema is not primed. Non-head live runs stay blocked."""
        plain = await _insert_batch(conn, run_uuid="run-plain", sync_type="incremental")
        await BatchQueue.update_status(conn, batch_id=plain, job_state="succeeded", attempt=1)

        head = await _insert_batch(conn, run_uuid="run-refresh", sync_type="full_refresh", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=head, job_state="succeeded", attempt=1)

        # Retire the plain run first so the cross-run gate isn't what hides it.
        await DuckgresBatchQueue.update_status(conn, batch_id=plain, job_state="failed", attempt=1)

        batches = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, blocked_schema_ids=["schema-1"])
        assert [str(b.id) for b in batches] == [head]

    @pytest.mark.asyncio
    async def test_eligible_schema_ids_restricts_claim_to_v3_schemas(self, conn):
        # The v3 allow-list must exclude a claimable (delta-succeeded, unblocked)
        # batch when its schema is not v3-enabled — the default batch is
        # full_refresh, which otherwise bypasses the unprimed block. Guards the
        # leak where non-v3 (e.g. Postgres) batches were applied via the
        # team-scoped claim. None = no filter (dev/tests); [] = nothing eligible.
        batch_id = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=batch_id, job_state="succeeded", attempt=1)

        async def claim(eligible: list[str] | None) -> list[Any]:
            return await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, eligible_schema_ids=eligible)

        assert len(await claim(None)) == 1
        assert len(await claim(["schema-1"])) == 1
        assert await claim(["other-schema"]) == []
        assert await claim([]) == []

    @pytest.mark.asyncio
    async def test_eligible_gate_excludes_replace_head_that_bypasses_block(self, conn):
        # A full_refresh replace-head bypasses the unprimed block, but the v3
        # allow-list must still exclude it when the schema is not v3-enabled — the
        # eligibility gate overrides the replace-head carve-out.
        head = await _insert_batch(conn, run_uuid="run-refresh", sync_type="full_refresh", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=head, job_state="succeeded", attempt=1)

        bypasses = await DuckgresBatchQueue.get_delta_succeeded_and_lock(conn, blocked_schema_ids=["schema-1"])
        assert [str(b.id) for b in bypasses] == [head]

        gated = await DuckgresBatchQueue.get_delta_succeeded_and_lock(
            conn, blocked_schema_ids=["schema-1"], eligible_schema_ids=["other-schema"]
        )
        assert gated == []
