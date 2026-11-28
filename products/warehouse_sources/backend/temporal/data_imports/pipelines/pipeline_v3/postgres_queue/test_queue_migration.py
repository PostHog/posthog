from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

import psycopg
import structlog

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue import queues
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (
    BatchConsumer,
    ConsumerConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    PostgresProducer,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult
from products.warehouse_sources_queue.backend.core.batch_consumer import OwnershipLostError
from products.warehouse_sources_queue.backend.core.jobs_db import BATCH_TABLE, LEASE_TABLE, BatchQueue
from products.warehouse_sources_queue.backend.core.queue_migration import (
    DrainingQueueLeases,
    claim_group_leases,
    get_drain_status,
)
from products.warehouse_sources_queue.backend.testing import (
    BATCH_DEFAULTS,
    ensure_queue_tables,
    get_test_database_url,
    truncate_queue_tables,
)

# The draining queue is a second table set in the test database, reached through search_path.
DRAINING_SCHEMA = "queue_migration_draining"
OWNER_A = str(uuid4())
OWNER_B = str(uuid4())
GROUP = (1, "schema-1")


@pytest.fixture(scope="module")
def active_url() -> str:
    return get_test_database_url()


@pytest.fixture(scope="module")
def draining_url(active_url: str) -> str:
    return f"{active_url}?options=-csearch_path%3D{DRAINING_SCHEMA}"


@pytest.fixture(autouse=True)
def _two_empty_queues(active_url: str, draining_url: str, settings: Any) -> None:
    with psycopg.Connection.connect(active_url, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {DRAINING_SCHEMA}")
    for url in (active_url, draining_url):
        with psycopg.Connection.connect(url, autocommit=True) as conn:
            ensure_queue_tables(conn)
            truncate_queue_tables(conn)
    settings.WAREHOUSE_SOURCES_DATABASE_URL = active_url
    settings.WAREHOUSE_SOURCES_DRAINING_DATABASE_URL = draining_url


@pytest.fixture
async def active(active_url: str):
    async with await psycopg.AsyncConnection.connect(active_url, autocommit=True) as c:
        yield c


@pytest.fixture
async def draining(draining_url: str):
    async with await psycopg.AsyncConnection.connect(draining_url, autocommit=True) as c:
        yield c


async def _insert(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str:
    return await BatchQueue.insert(conn, **{**BATCH_DEFAULTS, **overrides})


async def _claimed_schemas(conn: psycopg.AsyncConnection[Any], owner: str) -> set[str]:
    return {b.schema_id for b in await BatchQueue.get_unprocessed_and_lock(conn, owner_token=owner)}


def _consumer(active_url: str, draining_url: str) -> BatchConsumer:
    return BatchConsumer(
        config=ConsumerConfig(database_url=active_url),
        process_batch=AsyncMock(),
        draining_database_url=draining_url,
    )


async def _seed_free(draining: psycopg.AsyncConnection[Any]) -> None:
    pass


async def _seed_leased_by_another_loader(draining: psycopg.AsyncConnection[Any]) -> None:
    await claim_group_leases(draining, groups=[GROUP], owner_token=OWNER_B)


async def _seed_pending_batch(draining: psycopg.AsyncConnection[Any]) -> None:
    await _insert(draining)


async def _seed_batch_waiting_for_retry(draining: psycopg.AsyncConnection[Any]) -> None:
    batch_id = await _insert(draining)
    await BatchQueue.update_status(draining, batch_id=batch_id, job_state="waiting_retry", attempt=1)


async def _seed_executing_batch_whose_lease_expired(draining: psycopg.AsyncConnection[Any]) -> None:
    batch_id = await _insert(draining)
    await BatchQueue.update_status(draining, batch_id=batch_id, job_state="executing", attempt=1)
    await claim_group_leases(draining, groups=[GROUP], owner_token=OWNER_B)
    await draining.execute(f"UPDATE {LEASE_TABLE} SET expires_at = now() - interval '1 second'")


async def _seed_batch_of_a_failed_run(draining: psycopg.AsyncConnection[Any]) -> None:
    failed = await _insert(draining, batch_index=0)
    await _insert(draining, batch_index=1)
    await BatchQueue.update_status(draining, batch_id=failed, job_state="failed", attempt=1)


@pytest.mark.django_db(transaction=True)
class TestDrainingQueueLeases:
    @pytest.mark.parametrize(
        "seed, allowed",
        [
            (_seed_free, True),
            (_seed_leased_by_another_loader, False),
            (_seed_pending_batch, False),
            (_seed_batch_waiting_for_retry, False),
            # The old loader's lease lapsed mid-load, so only the batch state shows the group is busy.
            (_seed_executing_batch_whose_lease_expired, False),
            # The claim query never offers this batch again, so it must not hold the group forever.
            (_seed_batch_of_a_failed_run, True),
        ],
    )
    async def test_claim_allows_a_group_only_when_the_draining_queue_has_no_work_or_owner_for_it(
        self, draining, draining_url, seed, allowed
    ):
        await seed(draining)
        leases = DrainingQueueLeases(draining_url)
        try:
            assert (await leases.claim([GROUP], owner_token=OWNER_A)) == ({GROUP} if allowed else set())
            assert await leases.verify(team_id=1, schema_id="schema-1", owner_token=OWNER_A) is allowed
        finally:
            await leases.close()

    async def test_refused_group_stays_claimable_by_the_draining_loader(self, draining, draining_url):
        await _insert(draining)
        leases = DrainingQueueLeases(draining_url)
        try:
            await leases.claim([GROUP], owner_token=OWNER_A)
        finally:
            await leases.close()

        assert await _claimed_schemas(draining, OWNER_B) == {"schema-1"}


@pytest.mark.django_db(transaction=True)
class TestActiveLoaderDuringMigration:
    async def test_group_loads_from_the_draining_queue_before_the_active_queue(
        self, active, draining, active_url, draining_url
    ):
        await _insert(active, schema_id="schema-1", run_uuid="run-new")
        await _insert(active, schema_id="schema-2", run_uuid="run-other")
        old_batch = await _insert(draining, schema_id="schema-1", run_uuid="run-old")
        consumer = _consumer(active_url, draining_url)
        try:
            first = await consumer._fetch_batches(active, available=16)
            assert {b.schema_id for b in first} == {"schema-2"}

            assert await _claimed_schemas(draining, OWNER_B) == {"schema-1"}
            await BatchQueue.update_status(draining, batch_id=old_batch, job_state="succeeded", attempt=1)
            await BatchQueue.release_all_owned_leases(draining, owner_token=OWNER_B)

            second = await consumer._fetch_batches(active, available=16)
            assert "schema-1" in {b.schema_id for b in second}
        finally:
            await consumer._close()

    async def test_refused_group_keeps_no_lease_in_the_active_queue(self, active, draining, active_url, draining_url):
        await _insert(active, schema_id="schema-1", run_uuid="run-new")
        await claim_group_leases(draining, groups=[GROUP], owner_token=OWNER_B)
        consumer = _consumer(active_url, draining_url)
        try:
            assert await consumer._fetch_batches(active, available=16) == []
        finally:
            await consumer._close()

        async with active.cursor() as cur:
            await cur.execute(f"SELECT count(*) FROM {LEASE_TABLE}")
            assert (await cur.fetchone())[0] == 0

    async def test_losing_the_draining_lease_loses_ownership(self, active, draining, active_url, draining_url):
        await _insert(active, schema_id="schema-1", run_uuid="run-new")
        consumer = _consumer(active_url, draining_url)
        try:
            (batch,) = await consumer._fetch_batches(active, available=16)
            consumer._make_verify_ownership(batch)()

            await draining.execute(f"UPDATE {LEASE_TABLE} SET owner_token = %s", (OWNER_B,))

            renewed = await consumer._adapter.renew_lease(
                active, team_id=1, schema_id="schema-1", owner_token=consumer._owner_token, lease_ttl_seconds=300
            )
            assert renewed is False
            with pytest.raises(OwnershipLostError):
                consumer._make_verify_ownership(batch)()
        finally:
            await consumer._close()


@pytest.mark.django_db(transaction=True)
class TestProducerRouting:
    @pytest.mark.parametrize(
        "run_uuids, migrating, expected",
        [
            (("run-new",), True, "active"),
            (("run-old",), True, "draining"),
            # An attempt that resumes a run of the draining queue appends that run's final batch there.
            (("run-new", "run-old"), True, "draining"),
            (("run-old",), False, "active"),
        ],
    )
    async def test_run_stays_on_the_queue_that_holds_its_batches(
        self, draining, active_url, draining_url, settings, run_uuids, migrating, expected
    ):
        await _insert(draining, run_uuid="run-old")
        if not migrating:
            settings.WAREHOUSE_SOURCES_DRAINING_DATABASE_URL = ""

        assert queues.queue_url_for_run(*run_uuids) == {"active": active_url, "draining": draining_url}[expected]

    async def test_new_run_supersedes_an_older_attempt_left_in_the_draining_queue(self, draining, active_url):
        old_batch = await _insert(draining, job_id="job-1", run_uuid="run-old")
        producer = PostgresProducer(
            database_url=active_url,
            team_id=1,
            job_id="job-1",
            schema_id="schema-1",
            source_id="source-1",
            resource_name="test_resource",
            sync_type="full_refresh",
            run_uuid="run-new",
            logger=structlog.get_logger(),
        )
        producer.hold_batch(
            BatchWriteResult(batch_index=0, s3_path="s3://bucket/path", row_count=1, byte_size=1, timestamp_ns=1),
            cumulative_row_count=1,
        )

        async with draining.cursor() as cur:
            await cur.execute(f"SELECT superseded FROM {BATCH_TABLE} WHERE id = %s", (old_batch,))
            assert (await cur.fetchone())[0] is True


@pytest.mark.django_db(transaction=True)
class TestDrainStatus:
    @pytest.mark.parametrize(
        "is_final_batch, state, live_batches, open_runs, drained",
        [
            (False, None, 1, 1, False),
            # Every queued batch loaded, but the run has no final batch, so its producer can insert again.
            (False, "succeeded", 0, 1, False),
            (True, "succeeded", 0, 0, True),
        ],
    )
    async def test_queue_is_drained_only_when_nothing_waits_and_no_run_is_open(
        self, draining, draining_url, is_final_batch, state, live_batches, open_runs, drained
    ):
        batch_id = await _insert(draining, is_final_batch=is_final_batch)
        if state is not None:
            await BatchQueue.update_status(draining, batch_id=batch_id, job_state=state, attempt=1)

        with psycopg.Connection.connect(draining_url, autocommit=True) as conn:
            status = get_drain_status(conn)

        assert (status.live_batches, status.open_runs, status.drained) == (live_batches, open_runs, drained)
