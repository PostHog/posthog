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

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES
from posthog.models import PropertyDefinition, Team
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySyncRunRecord,
    PersonPropertySyncSource,
    person_property_sync_sources_for,
    record_person_property_sync_run,
)
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    delta_storage_options,
)

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "customer_analytics_person_property_sync"


@dataclasses.dataclass
class PerSourceResult:
    """One source's funnel counts within a run, so the recorder can persist a run row per source."""

    source_id: str
    rows_read: int = 0
    changed: int = 0
    existing: int = 0
    produced: int = 0
    skipped_missing_person: int = 0


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
    per_source: list[PerSourceResult] = dataclasses.field(default_factory=list)


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


def _snapshot_prefix(team_id: int, schema_id: str, source_id: str) -> str:
    # A folder, not a single file: each run drops a uniquely-named parquet of the hashes it produced,
    # and the reader unions every file in the folder. Two writers (a scheduled sync and a backfill)
    # for the same source can't clobber each other, since they write different filenames. Growth is
    # bounded by _write_snapshot_hashes, which compacts the folder back down as it writes.
    return f"{settings.DATAWAREHOUSE_BUCKET}/person_property_snapshot/{team_id}/{source_id}/{schema_id}"


async def _read_staged_rows(team_id: int, schema_id: str, job_id: str) -> list[dict]:
    prefix = _staged_prefix(team_id, schema_id, job_id)
    rows: list[dict] = []
    async with aget_s3_client() as s3_client:
        try:
            listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
        except FileNotFoundError:
            # No staged folder — the sync staged nothing for this run (common on a no-change sync).
            logger.debug("person-property sync: no staged rows folder", team_id=team_id, schema_id=schema_id)
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


def _snapshot_file_order(entry: dict) -> tuple:
    # Oldest first, so a newer run's hashes win for a repeated distinct_id. Order by the file's
    # last-modified time (the run that wrote it), falling back to the key when a store omits the
    # timestamp. The (is-missing, time, key) shape keeps None timestamps sorting first without ever
    # comparing None to a datetime.
    last_modified = entry.get("LastModified")
    return (last_modified is None, last_modified, entry["Key"])


def _s3_uri(key: str) -> str:
    return key if key.startswith("s3://") else f"s3://{key}"


def _s3_key(key: str) -> str:
    # Normalize an ``_ls`` key or a path we built for equality checks: drop any scheme and leading slash.
    return key.removeprefix("s3://").lstrip("/")


async def _list_snapshot_files(s3_client, prefix: str) -> list[str]:
    """S3 keys of the source's snapshot files, oldest first (see ``_snapshot_file_order``). Empty when
    the folder doesn't exist yet."""
    try:
        listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
    except FileNotFoundError:
        return []
    values = listing.values() if isinstance(listing, dict) else listing
    files = sorted((f for f in values if f.get("type") != "directory"), key=_snapshot_file_order)
    return [f["Key"] for f in files]


async def _merge_snapshot_files(s3_client, file_keys: list[str]) -> dict[str, str]:
    """Union the given snapshot files into {distinct_id: sent_hash}, later files winning (callers pass
    them oldest-first). Decodes off the event loop so a large parquet can't starve the heartbeater."""
    hashes: dict[str, str] = {}
    for key in file_keys:
        data = await s3_client._cat_file(_s3_uri(key))
        for record in await asyncio.to_thread(_decode_parquet_rows, data):
            hashes[record["distinct_id"]] = record["sent_hash"]
    return hashes


async def _read_snapshot_hashes(team_id: int, schema_id: str, source_id: str) -> dict[str, str]:
    """Union every parquet file in the source's snapshot folder into {distinct_id: sent_hash}, reading
    oldest file first so a newer run's hash wins for a repeated distinct_id (a stale hash would only
    cost an idempotent re-send, but newest-wins avoids even that). Ordering never affects correctness."""
    prefix = _snapshot_prefix(team_id, schema_id, source_id)
    async with aget_s3_client() as s3_client:
        return await _merge_snapshot_files(s3_client, await _list_snapshot_files(s3_client, prefix))


async def _write_snapshot_hashes(
    team_id: int, schema_id: str, source_id: str, run_token: str, hashes: dict[str, str]
) -> None:
    """Persist this run's produced ``hashes`` and compact the source's snapshot folder in one pass.
    Writes the union of every existing snapshot file and ``hashes`` into ``{run_token}.parquet`` (this
    run's values winning), then deletes the other files it merged. Compacting on the write path bounds
    the folder to roughly one file per run instead of one more file every run — otherwise the reader
    would download and decode the whole unbounded history on every later run, and a warehouse editor
    could grow it (by repeatedly changing rows and syncing) until a metadata activity exhausts S3
    requests, memory, or its timeout. Concurrency-safe: a file a concurrent writer adds after this
    listing isn't in the merge set, so it's neither merged-away nor deleted, and its rows still surface
    through the reader's union; the two files collapse on the next run. Write-then-delete keeps a crash
    between the two harmless — the reader unions both the new file and the not-yet-deleted old ones."""
    import pyarrow as pa  # noqa: PLC0415

    prefix = _snapshot_prefix(team_id, schema_id, source_id)
    write_path = f"{prefix}/{run_token}.parquet"
    async with aget_s3_client() as s3_client:
        existing_keys = await _list_snapshot_files(s3_client, prefix)
        merged = await _merge_snapshot_files(s3_client, existing_keys)
        merged.update(hashes)

        table = pa.table({"distinct_id": list(merged.keys()), "sent_hash": list(merged.values())})
        buffer = pa.BufferOutputStream()
        pq.write_table(table, buffer, compression="zstd")
        await s3_client._pipe_file(_s3_uri(write_path), buffer.getvalue().to_pybytes())

        # Delete the files we merged, except the one we just wrote (the backfill token reuses its name).
        stale = [key for key in existing_keys if _s3_key(key) != _s3_key(write_path)]
        if stale:
            try:
                await s3_client._rm([_s3_uri(key) for key in stale])
            except FileNotFoundError:
                pass


async def _clear_staged(team_id: int, schema_id: str, job_id: str) -> None:
    prefix = _staged_prefix(team_id, schema_id, job_id)
    async with aget_s3_client() as s3_client:
        try:
            await s3_client._rm(f"s3://{prefix}/", recursive=True)
        except FileNotFoundError:
            pass


def _get_schema(team_id: int, schema_id: str) -> ExternalDataSchema | None:
    # select_related the source so folder_path() (which reads source.source_type) doesn't lazy-load.
    # exclude(deleted=True) matches the rest of the codebase's schema lookups — a soft-deleted schema
    # (source removed) must not be backfilled against.
    return (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(id=schema_id, team_id=team_id)
        .select_related("source")
        .first()
    )


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


async def _process_source_bundles(
    *,
    team_id: int,
    schema_id: str,
    team_api_token: str,
    source: PersonPropertySyncSource,
    bundles: list[tuple[str, dict]],
    rows_read: int,
    run_token: str,
) -> PerSourceResult:
    """Diff one source's bundles against its snapshot, drop non-existing persons, produce $set intents,
    stamp provenance, and advance the snapshot. Shared by the incremental sync and the backfill — they
    differ only in how ``bundles`` are sourced (staged rows vs a full Delta read)."""
    ps = PerSourceResult(source_id=str(source.source_id), rows_read=rows_read)
    prior = await _read_snapshot_hashes(team_id, schema_id, str(source.source_id))
    changed, new_hashes = select_changed(bundles, prior)
    ps.changed = len(changed)
    if not changed:
        return ps

    existing = await database_sync_to_async(_filter_existing_persons, thread_sensitive=False)(
        team_id, [distinct_id for distinct_id, _ in changed]
    )
    to_send = [(distinct_id, bundle) for distinct_id, bundle in changed if distinct_id in existing]
    ps.existing = len(to_send)
    ps.skipped_missing_person = len(changed) - len(to_send)
    if not to_send:
        logger.info(
            "person-property sync: no existing persons among changed rows for source",
            team_id=team_id,
            schema_id=schema_id,
            source_id=str(source.source_id),
            changed=len(changed),
        )
        return ps

    produced = await asyncio.to_thread(_produce_intents, team_id, team_api_token, to_send)
    ps.produced = produced

    # Stamp provenance before advancing the snapshot: the snapshot is the checkpoint that makes
    # these rows look unchanged on the next run, so anything that must accompany a produce has to
    # happen first. Stamping is an idempotent update, safe to repeat if a retry re-produces.
    await database_sync_to_async(_stamp_provenance, thread_sensitive=False)(
        team_id, schema_id, source, list((source.column_property_map or {}).values())
    )

    # Record only the distinct_ids we actually produced, as this run's snapshot file.
    sent_ids = {distinct_id for distinct_id, _ in to_send}
    produced_hashes = {d: h for d, h in new_hashes.items() if d in sent_ids}
    await _write_snapshot_hashes(team_id, schema_id, str(source.source_id), run_token, produced_hashes)

    logger.info(
        "person-property sync: source processed",
        team_id=team_id,
        schema_id=schema_id,
        source_id=str(source.source_id),
        bundles=len(bundles),
        changed=len(changed),
        existing=len(to_send),
        produced=produced,
    )
    return ps


def _accumulate(result: SyncResult, ps: PerSourceResult) -> None:
    result.per_source.append(ps)
    result.changed += ps.changed
    result.existing += ps.existing
    result.produced += ps.produced
    result.skipped_missing_person += ps.skipped_missing_person


async def run_person_property_sync(*, team_id: int, schema_id: str, job_id: str) -> SyncResult:
    result = SyncResult()
    sources = await database_sync_to_async(person_property_sync_sources_for, thread_sensitive=False)(team_id, schema_id)
    if not sources:
        logger.info(
            "person-property sync: no enabled person sources for schema, nothing to do",
            team_id=team_id,
            schema_id=str(schema_id),
            job_id=job_id,
        )
        return result

    team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=team_id)
    rows = await _read_staged_rows(team_id, str(schema_id), job_id)
    result.sources = len(sources)
    result.rows_read = len(rows)
    logger.info(
        "person-property sync: read staged rows",
        team_id=team_id,
        schema_id=str(schema_id),
        job_id=job_id,
        sources=len(sources),
        rows_read=len(rows),
    )

    for source in sources:
        bundles = build_bundles(rows, source.key_column, source.column_property_map or {})
        ps = await _process_source_bundles(
            team_id=team_id,
            schema_id=str(schema_id),
            team_api_token=team.api_token,
            source=source,
            bundles=bundles,
            rows_read=len(rows),
            run_token=job_id,
        )
        _accumulate(result, ps)

    await _clear_staged(team_id, str(schema_id), job_id)
    return result


# --- backfill (full Delta read) ----------------------------------------------------------

# Rows per streamed Delta batch. Batches are processed then discarded, so peak memory is one batch
# plus the per-source {distinct_id: bundle} accumulator (bounded by distinct-person cardinality).
BACKFILL_BATCH_SIZE = 50_000

# Backfill runs share one snapshot filename per source (a full-table read replaces the whole set),
# distinct from the incremental job-id filenames, so the two writers never collide.
BACKFILL_RUN_TOKEN = "backfill"


def _read_delta_bundles(
    uri: str, storage_options: dict[str, str], sources: list[PersonPropertySyncSource]
) -> tuple[dict[str, dict[str, dict]], int]:
    """Stream the table's Delta files from S3 and accumulate {source_id: {distinct_id: bundle}}
    (last-write-wins per distinct_id). Streams batches — never materializes the whole table — so peak
    memory tracks distinct persons, not row count. Returns (accumulated, rows_read)."""
    import deltalake  # noqa: PLC0415 — keeps the heavy delta-rs/pandas stack off the import path

    accumulated: dict[str, dict[str, dict]] = {str(source.source_id): {} for source in sources}
    if not deltalake.DeltaTable.is_deltatable(uri, storage_options=storage_options):
        # No Delta table at the expected URI yet (e.g. the source's first sync hasn't landed) — treat
        # as an empty read rather than erroring, but log it since a persistent empty backfill is a
        # likely "why didn't anything happen" answer.
        logger.warning("person-property backfill: no Delta table at URI, reading 0 rows", uri=uri)
        return accumulated, 0

    dataset = deltalake.DeltaTable(uri, storage_options=storage_options).to_pyarrow_dataset()
    available = set(dataset.schema.names)
    wanted = {
        column for source in sources for column in (source.key_column, *(source.column_property_map or {}).keys())
    }
    # Project only columns that exist — a misconfigured column drops out rather than erroring.
    project = sorted(wanted & available)

    # A source whose key column itself is missing produces zero bundles for the whole table, which is
    # otherwise indistinguishable from a genuinely idle backfill. Log it so a misconfigured mapping
    # (table dropped/renamed the identifier column) is diagnosable rather than silent.
    for source in sources:
        if source.key_column not in available:
            logger.warning(
                "person-property backfill: source key column missing from table, will produce nothing",
                uri=uri,
                source_id=str(source.source_id),
                key_column=source.key_column,
            )

    rows_read = 0
    for batch in dataset.to_batches(columns=project, batch_size=BACKFILL_BATCH_SIZE):
        rows = batch.to_pylist()
        rows_read += len(rows)
        for source in sources:
            bucket = accumulated[str(source.source_id)]
            for distinct_id, bundle in build_bundles(rows, source.key_column, source.column_property_map or {}):
                bucket[distinct_id] = bundle
    return accumulated, rows_read


async def run_person_property_backfill(*, team_id: int, schema_id: str, trigger: str) -> SyncResult:
    """Populate person properties from a warehouse table's full Delta data (rather than the
    incrementally staged rows) — for a new/changed mapping that never saw historical rows. Reads the
    table once and upserts every enabled person source on the schema; the snapshot diff still skips
    unchanged values, so re-running is cheap."""
    result = SyncResult()
    sources = await database_sync_to_async(person_property_sync_sources_for, thread_sensitive=False)(team_id, schema_id)
    if not sources:
        logger.info(
            "person-property backfill: no enabled person sources for schema, nothing to do",
            team_id=team_id,
            schema_id=str(schema_id),
            trigger=trigger,
        )
        return result

    schema = await database_sync_to_async(_get_schema, thread_sensitive=False)(team_id, schema_id)
    if schema is None:
        logger.warning(
            "person-property backfill: schema no longer exists, nothing to do",
            team_id=team_id,
            schema_id=str(schema_id),
            trigger=trigger,
        )
        return result

    team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=team_id)
    # Resolve the Delta folder leaf the same way the loader wrote it: `resolved_s3_folder_name`
    # (or the schema name) normalized, never `normalized_name`. For schema-qualified/migration-pinned
    # sources (e.g. Postgres `public.users` → folder `users`) these diverge, and `normalized_name`
    # would point at a prefix with no Delta log — a silent 0-row no-op.
    folder_leaf = NamingConvention.normalize_identifier(schema.resolved_s3_folder_name or schema.name)
    uri = f"{settings.BUCKET_URL}/{schema.folder_path()}/{folder_leaf}"
    accumulated, rows_read = await asyncio.to_thread(_read_delta_bundles, uri, delta_storage_options(), sources)
    result.sources = len(sources)
    result.rows_read = rows_read
    logger.info(
        "person-property backfill: read full Delta table",
        team_id=team_id,
        schema_id=str(schema_id),
        trigger=trigger,
        sources=len(sources),
        rows_read=rows_read,
    )

    for source in sources:
        bundles = list(accumulated[str(source.source_id)].items())
        ps = await _process_source_bundles(
            team_id=team_id,
            schema_id=str(schema_id),
            team_api_token=team.api_token,
            source=source,
            bundles=bundles,
            rows_read=rows_read,
            run_token=BACKFILL_RUN_TOKEN,
        )
        _accumulate(result, ps)

    return result


# --- run recording (persisted history) ---------------------------------------------------


def _record(
    *,
    team_id: int,
    schema_id: str,
    job_id: str | None,
    trigger: str,
    status: str,
    started_at: str,
    finished_at: str,
    ps: PerSourceResult,
    error: str | None,
) -> None:
    record_person_property_sync_run(
        PersonPropertySyncRunRecord(
            team_id=team_id,
            schema_id=schema_id,
            source_id=ps.source_id,
            job_id=job_id,
            trigger=trigger,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            rows_read=ps.rows_read,
            changed=ps.changed,
            existing=ps.existing,
            produced=ps.produced,
            skipped_missing_person=ps.skipped_missing_person,
            error=error,
        )
    )


async def record_completed_runs(
    *,
    team_id: int,
    schema_id: str,
    job_id: str | None,
    trigger: str,
    started_at: str,
    finished_at: str,
    result: SyncResult,
) -> None:
    """Persist one completed run row per source. Never raises — the recorder swallows its own errors,
    and we still guard here so run bookkeeping can't fail the sync/backfill that produced it (which
    would otherwise trigger a wasteful Temporal retry of an already-successful, produced run)."""
    try:
        for ps in result.per_source:
            await database_sync_to_async(_record, thread_sensitive=False)(
                team_id=team_id,
                schema_id=schema_id,
                job_id=job_id,
                trigger=trigger,
                status="completed",
                started_at=started_at,
                finished_at=finished_at,
                ps=ps,
                error=None,
            )
    except Exception as e:
        logger.exception(
            "person-property run: failed to record completed runs",
            team_id=team_id,
            schema_id=schema_id,
            job_id=job_id,
            trigger=trigger,
        )
        capture_exception(e, {"team_id": team_id, "schema_id": schema_id, "trigger": trigger})


async def record_failed_runs(
    *, team_id: int, schema_id: str, job_id: str | None, trigger: str, started_at: str, finished_at: str, error: str
) -> None:
    """Persist a failed run row per source the schema feeds, so a failure is visible in the UI (not
    only in error tracking). Never raises — this runs on the already-failing path, so any error here
    (a bad DB state while resolving sources, or the record write itself) is captured, not propagated,
    to avoid masking the original failure that Temporal needs to see."""
    try:
        sources = await database_sync_to_async(person_property_sync_sources_for, thread_sensitive=False)(
            team_id, schema_id
        )
        for source in sources or []:
            await database_sync_to_async(_record, thread_sensitive=False)(
                team_id=team_id,
                schema_id=schema_id,
                job_id=job_id,
                trigger=trigger,
                status="failed",
                started_at=started_at,
                finished_at=finished_at,
                ps=PerSourceResult(source_id=str(source.source_id)),
                error=error,
            )
    except Exception as e:
        logger.exception(
            "person-property run: failed to record failed runs",
            team_id=team_id,
            schema_id=schema_id,
            job_id=job_id,
            trigger=trigger,
        )
        capture_exception(e, {"team_id": team_id, "schema_id": schema_id, "trigger": trigger})
