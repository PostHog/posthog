"""Upsert warehouse columns onto person properties from the rows a sync staged to S3.

Runs in a post-sync Temporal activity (see data_imports/person_property_sync_job.py). Per enabled
person-target source for the schema it:

1. reads the staged parquet (already just this run's changed rows),
2. builds each row's {property: value} bundle keyed by distinct_id,
3. diffs against the source's last-sent snapshot (S3) so unchanged values are skipped even on a
   full refresh,
4. drops distinct_ids that don't resolve to an existing person (personhog),
5. produces one $set intent per survivor to Kafka (a throttling consumer sends them to capture),
6. updates the snapshot, stamps provenance on the person PropertyDefinitions, and clears the staged
   files.

The source configs (key column + column -> property map) are resolved through the
``person_property_sync_sources_for`` hook so this module never imports the customer_analytics
config models. The pure functions (bundle building, hashing, diff) are unit-tested directly; the
S3/personhog/Kafka helpers are the boundaries and are mocked in the orchestration test.
"""

import json
import asyncio
import hashlib
import dataclasses

from django.conf import settings

import structlog
import pyarrow.parquet as pq

from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES
from posthog.models import PropertyDefinition, Team
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySyncSource,
    person_property_sync_sources_for,
)

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "customer_analytics_person_property_sync"


@dataclasses.dataclass
class SyncResult:
    sources: int = 0
    rows_read: int = 0
    changed: int = 0
    existing: int = 0
    produced: int = 0
    # Changed rows dropped because their distinct_id resolved to no existing person. The most
    # common "why didn't my property update" answer, so it's tracked and reported explicitly.
    skipped_missing_person: int = 0


# --- pure core ---------------------------------------------------------------------------


def bundle_hash(bundle: dict) -> str:
    """Stable hash of a {property: value} bundle. sort_keys + default=str so re-ordering or
    non-JSON scalars (datetimes) don't spuriously look changed.

    The hash covers the source's whole bundle (all of its mapped properties for one person), not
    each property individually — one changed column re-sends every property the source maps for
    that person. That's deliberately coarse: re-`$set`ting an unchanged value is a no-op, and one
    hash per (source, distinct_id) keeps the snapshot a flat two-column parquet."""
    return hashlib.sha256(json.dumps(bundle, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def build_bundles(rows: list[dict], key_column: str, column_property_map: dict[str, str]) -> list[tuple[str, dict]]:
    """(distinct_id, {person_property: value}) for each row with a non-null key and at least one
    non-null mapped value. Missing columns are simply absent (a misconfigured source degrades to
    fewer properties rather than erroring)."""
    bundles: list[tuple[str, dict]] = []
    for row in rows:
        key = row.get(key_column)
        if key is None:
            continue
        bundle = {prop: row[col] for col, prop in column_property_map.items() if row.get(col) is not None}
        if bundle:
            bundles.append((str(key), bundle))
    return bundles


def select_changed(
    bundles: list[tuple[str, dict]], prior_hashes: dict[str, str]
) -> tuple[list[tuple[str, dict]], dict[str, str]]:
    """Keep only bundles whose hash differs from the snapshot. Returns (changed, hashes-for-changed).
    Last write wins when a distinct_id appears twice in one run."""
    changed: list[tuple[str, dict]] = []
    new_hashes: dict[str, str] = {}
    seen: set[str] = set()
    for distinct_id, bundle in bundles:
        current = bundle_hash(bundle)
        if prior_hashes.get(distinct_id) == current and distinct_id not in new_hashes:
            continue
        if distinct_id in seen:
            # replace the earlier bundle for this run with the later one
            changed = [(d, b) for d, b in changed if d != distinct_id]
        changed.append((distinct_id, bundle))
        new_hashes[distinct_id] = current
        seen.add(distinct_id)
    return changed, new_hashes


# --- S3 / Kafka / personhog boundaries (mocked in tests) ---------------------------------


def _staged_prefix(team_id: int, schema_id: str, job_id: str) -> str:
    return f"{settings.DATAWAREHOUSE_BUCKET}/person_property_sync/{team_id}/{schema_id}/{job_id}"


def _snapshot_path(team_id: int, schema_id: str, source_id: str) -> str:
    return f"{settings.DATAWAREHOUSE_BUCKET}/person_property_snapshot/{team_id}/{source_id}/{schema_id}.parquet"


async def _read_staged_rows(team_id: int, schema_id: str, job_id: str) -> list[dict]:
    prefix = _staged_prefix(team_id, schema_id, job_id)
    rows: list[dict] = []
    async with aget_s3_client() as s3_client:
        try:
            listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
        except FileNotFoundError:
            return []
        values = listing.values() if isinstance(listing, dict) else listing
        files = [f["Key"] for f in values if f.get("type") != "directory"]
        for file_path in files:
            data = await s3_client._cat_file(f"s3://{file_path}" if not file_path.startswith("s3://") else file_path)
            # Decode off the event loop: a large parquet chunk would otherwise block the async
            # activity long enough to starve the heartbeater and trip its timeout.
            rows.extend(await asyncio.to_thread(_decode_parquet_rows, data))
    return rows


def _bytes_reader(data: bytes):
    import io  # noqa: PLC0415 — local to keep the module import light

    return io.BytesIO(data)


def _decode_parquet_rows(data: bytes) -> list[dict]:
    return pq.read_table(_bytes_reader(data)).to_pylist()


async def _read_snapshot_hashes(team_id: int, schema_id: str, source_id: str) -> dict[str, str]:
    path = _snapshot_path(team_id, schema_id, source_id)
    async with aget_s3_client() as s3_client:
        try:
            data = await s3_client._cat_file(f"s3://{path}")
        except FileNotFoundError:
            return {}
    records = await asyncio.to_thread(_decode_parquet_rows, data)
    return {r["distinct_id"]: r["sent_hash"] for r in records}


async def _write_snapshot_hashes(team_id: int, schema_id: str, source_id: str, hashes: dict[str, str]) -> None:
    import pyarrow as pa  # noqa: PLC0415

    path = _snapshot_path(team_id, schema_id, source_id)
    table = pa.table({"distinct_id": list(hashes.keys()), "sent_hash": list(hashes.values())})
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer, compression="zstd")
    async with aget_s3_client() as s3_client:
        await s3_client._pipe_file(f"s3://{path}", buffer.getvalue().to_pybytes())


async def _clear_staged(team_id: int, schema_id: str, job_id: str) -> None:
    prefix = _staged_prefix(team_id, schema_id, job_id)
    async with aget_s3_client() as s3_client:
        try:
            await s3_client._rm(f"s3://{prefix}/", recursive=True)
        except FileNotFoundError:
            pass


def _filter_existing_persons(team_id: int, distinct_ids: list[str]) -> set[str]:
    if not distinct_ids:
        return set()
    return set(get_persons_mapped_by_distinct_id(team_id, distinct_ids).keys())


def _produce_intents(team_id: int, token: str, items: list[tuple[str, dict]]) -> int:
    """Produce one $set intent per person to Kafka, keyed by team:distinct_id so the consumer can
    throttle per team and preserve per-person ordering. Returns the count produced."""
    produced = 0
    with producer_scope(topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES) as producer:
        for distinct_id, bundle in items:
            producer.produce(
                topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES,
                data={
                    "team_id": team_id,
                    "token": token,
                    "distinct_id": distinct_id,
                    "properties": bundle,
                    "event_source": EVENT_SOURCE,
                },
                key=f"{team_id}:{distinct_id}",
            )
            produced += 1
    return produced


def _stamp_provenance(
    team_id: int, schema_id: str, source: PersonPropertySyncSource, property_names: list[str]
) -> None:
    # UPDATE-only on purpose: definitions are created by ingestion's propdef upsert when the $set
    # lands, so a brand-new property may not have a row yet on the first sync — the next sync's
    # stamp catches it. Never inserting means this can't race that upsert.
    origin = {
        "source_id": str(source.definition_id),
        "schema_id": str(schema_id),
        "custom_property_source_id": str(source.source_id),
    }
    PropertyDefinition.objects.filter(
        team_id=team_id, type=PropertyDefinition.Type.PERSON, name__in=property_names
    ).update(warehouse_origin=origin)


# --- orchestration -----------------------------------------------------------------------


async def run_person_property_sync(*, team_id: int, schema_id: str, job_id: str) -> SyncResult:
    result = SyncResult()
    sources = await database_sync_to_async(person_property_sync_sources_for, thread_sensitive=False)(team_id, schema_id)
    if not sources:
        return result

    team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=team_id)
    rows = await _read_staged_rows(team_id, str(schema_id), job_id)
    result.sources = len(sources)
    result.rows_read = len(rows)

    for source in sources:
        bundles = build_bundles(rows, source.key_column, source.column_property_map or {})
        prior = await _read_snapshot_hashes(team_id, str(schema_id), str(source.source_id))
        changed, new_hashes = select_changed(bundles, prior)
        result.changed += len(changed)
        if not changed:
            continue

        existing = await database_sync_to_async(_filter_existing_persons, thread_sensitive=False)(
            team_id, [distinct_id for distinct_id, _ in changed]
        )
        to_send = [(distinct_id, bundle) for distinct_id, bundle in changed if distinct_id in existing]
        result.existing += len(to_send)
        result.skipped_missing_person += len(changed) - len(to_send)
        if not to_send:
            logger.info(
                "person-property sync: no existing persons among changed rows for source",
                team_id=team_id,
                schema_id=str(schema_id),
                source_id=str(source.source_id),
                changed=len(changed),
            )
            continue

        produced = await asyncio.to_thread(_produce_intents, team_id, team.api_token, to_send)
        result.produced += produced

        # Stamp provenance before advancing the snapshot: the snapshot is the checkpoint that makes
        # these rows look unchanged on the next run, so anything that must accompany a produce has to
        # happen first. Stamping is an idempotent update, safe to repeat if a retry re-produces.
        await database_sync_to_async(_stamp_provenance, thread_sensitive=False)(
            team_id, str(schema_id), source, list((source.column_property_map or {}).values())
        )

        # Only advance the snapshot for distinct_ids we actually produced.
        sent_ids = {distinct_id for distinct_id, _ in to_send}
        merged = {**prior, **{d: h for d, h in new_hashes.items() if d in sent_ids}}
        await _write_snapshot_hashes(team_id, str(schema_id), str(source.source_id), merged)

        logger.info(
            "person-property sync: source processed",
            team_id=team_id,
            schema_id=str(schema_id),
            source_id=str(source.source_id),
            bundles=len(bundles),
            changed=len(changed),
            existing=len(to_send),
            produced=produced,
        )

    await _clear_staged(team_id, str(schema_id), job_id)
    return result
