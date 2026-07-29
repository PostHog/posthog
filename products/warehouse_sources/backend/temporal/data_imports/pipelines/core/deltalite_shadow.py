"""Shadow-mode verification for the deltalite streaming upsert (rollout canary, phase 1).

deltalite is a Rust library that replaces delta-rs's SQL MERGE for the incremental sync with a
streaming partition-level upsert. Before it ever writes a production table, we want evidence that it
produces byte-for-byte the same result as the merge on real customer data. This module provides that
evidence with ZERO blast radius: for an eligible incremental batch, after the real merge has already
committed the true table, it re-applies the SAME batch through deltalite into a *throwaway copy* of
just the affected partitions and compares the two. deltalite never touches the real table.

Flow (see the rollout plan):
  1. The real delta-rs MERGE has already run → the real table is at version N+1. The caller captured
     the pre-merge version N.
  2. Seed a throwaway Delta table at state N, scoped to the batch's affected partition values, by
     time-travelling the real table to version N and copying only those partitions.
  3. Run ``deltalite.upsert(batch)`` into the throwaway table.
  4. Compare the affected partitions of the real table @ N+1 (ground truth) against the throwaway
     table via a DuckDB set-difference. Rows outside the affected partitions are untouched by both the
     merge and deltalite, so comparing only the affected partition values is exact.
  5. Emit a ``match`` / ``mismatch`` / ``skipped`` / ``unsupported`` / ``error`` metric, then delete
     the throwaway prefix.

Everything here is best-effort. A shadow failure MUST NOT affect the real sync — the caller wraps the
invocation in a broad ``try/except`` and treats any exception as an ignored shadow error. The
``deltalite`` import is guarded so the module is inert (records nothing but an ``error`` metric) until
the wheel is published + pinned by the ``build-deltalite`` workflow at rollout time.
"""

from __future__ import annotations

import hmac
import random
import asyncio
import hashlib
from collections.abc import Sequence
from typing import Any

from django.conf import settings

import duckdb
import pyarrow as pa
import deltalake
import pyarrow.compute as pc
import posthoganalytics
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper import _purge_s3_prefix
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTALITE_SHADOW_DURATION_SECONDS,
    DELTALITE_SHADOW_TOTAL,
)

# `deltalake` and `duckdb` are hard dependencies (the merge path and the comparison engine),
# imported normally. deltalite is NOT a dependency yet — the wheel is published + pinned by the
# `build-deltalite` workflow at rollout time — so its import is guarded: this module, and therefore
# the sync, is unaffected when the wheel isn't installed.
try:
    import deltalite

    _DELTALITE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where the wheel isn't installed
    deltalite = None  # ty: ignore[invalid-assignment]
    _DELTALITE_AVAILABLE = False


WAREHOUSE_DELTALITE_SHADOW_FLAG = "data-warehouse-deltalite-shadow"

# Suffix for the throwaway copy. Includes the run so concurrent syncs of the same table never collide,
# and is easy to grep/lifecycle-sweep. Lives under the same bucket as the real table.
_SHADOW_SUFFIX = "__deltalite_shadow"


def is_deltalite_shadow_enabled(team_id: int, schema_id: str, source_type: str | None = None) -> bool:
    """Evaluate the per-schema shadow rollout flag.

    ``schema_id`` (and ``team_id`` / ``source_type``) are passed as person properties so the flag can
    be released to a single table first — set a release condition ``schema_id = <id>`` to shadow one
    schema before ramping by team / org / source. Mirrors ``is_auto_repartition_enabled``.

    Any evaluation failure returns False (fail closed): a flags-service blip must never accidentally
    switch the shadow on.
    """
    from posthog.models import Team

    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    except Team.DoesNotExist:
        return False

    # Resolve source_type from the schema when the caller didn't supply it, so a `source_type = <x>`
    # release condition can actually match (mirrors is_auto_repartition_enabled). Best-effort: a lookup
    # failure just omits the property rather than failing the whole check.
    if source_type is None:
        try:
            from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
            source_type = schema.source.source_type
        except Exception:
            source_type = None

    person_properties: dict[str, str] = {"schema_id": str(schema_id), "team_id": str(team_id)}
    if source_type is not None:
        person_properties["source_type"] = source_type

    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_DELTALITE_SHADOW_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team_id)},
                person_properties=person_properties,
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team_id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def _record(outcome: str) -> None:
    DELTALITE_SHADOW_TOTAL.labels(outcome=outcome).inc()


def _pk_digest(row: Sequence[Any]) -> str:
    """Keyed, truncated digest of one primary-key tuple, safe to log.

    HMAC-SHA256 with the server secret so a low-entropy key (a small integer ID, an email) can't be
    recovered by brute-forcing the hash from log access; the key is stable across runs/processes so the
    same PK always maps to the same digest for cross-run correlation.
    """
    payload = "\x1f".join(map(str, row)).encode()
    return hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()[:12]


def _affected_partition_values(data: pa.Table, partition_key: str | None) -> list[str] | None:
    """Distinct partition values in the batch, or None when the table is unpartitioned (= whole table)."""
    if partition_key is None or partition_key not in data.column_names:
        return None
    return [v.as_py() for v in pc.unique(data[partition_key])]


def _affected_at_rest_stats(
    uri: str, storage_options: dict[str, str], version: int, affected: list[str] | None
) -> tuple[int, int] | None:
    """Compressed on-S3 size and row count of the affected partitions at ``version``, from Delta stats.

    Metadata only — no data is read. Used to skip oversized batches cheaply before anything is
    materialized. Returns ``(compressed_bytes, rows)``, or ``None`` when the stats can't be read so the
    caller can fail closed (skip) rather than materialize an unbounded slice into worker memory.

    ``rows`` bounds the *uncompressed* working set the way ``compressed_bytes`` can't: a highly
    compressible partition is tiny on S3 but explodes once decompressed into the Arrow comparison, so
    a small at-rest size alone doesn't prove the batch is safe to shadow.
    """
    try:
        dt = deltalake.DeltaTable(uri, version=version, storage_options=storage_options)
        # get_add_actions returns an arro3 Table; read columns via its own API and sum in Python
        # (a table has a few hundred files at most, so this is cheap and avoids arrow-compute typing).
        adds = dt.get_add_actions(flatten=True)
        if "size_bytes" not in adds.column_names or "num_records" not in adds.column_names:
            return None
        sizes = adds["size_bytes"].to_pylist()
        records = adds["num_records"].to_pylist()
        if affected is None:
            return sum(int(s or 0) for s in sizes), sum(int(r or 0) for r in records)
        part_col_name = f"partition.{PARTITION_KEY}"
        if part_col_name not in adds.column_names:
            # Partitioned read requested but the partition column is absent from the stats — we can't
            # scope the estimate, so treat it as unknown and let the caller fail closed.
            return None
        parts = adds[part_col_name].to_pylist()
        affected_set = {str(a) for a in affected}
        return (
            sum(int(s or 0) for s, p in zip(sizes, parts) if str(p) in affected_set),
            sum(int(r or 0) for r, p in zip(records, parts) if str(p) in affected_set),
        )
    except Exception:
        return None


def _read_affected(
    uri: str, storage_options: dict[str, str], version: int | None, affected: list[str] | None
) -> pa.Table:
    """Read the affected partitions of the table (at ``version`` if given, else latest)."""
    dt = deltalake.DeltaTable(uri, version=version, storage_options=storage_options)
    if affected is None:
        return dt.to_pyarrow_table()
    return dt.to_pyarrow_table(partitions=[(PARTITION_KEY, "in", [str(a) for a in affected])])


def _seed_shadow(seed: pa.Table, shadow_uri: str, storage_options: dict[str, str], partition_key: str | None) -> None:
    deltalake.write_deltalake(
        shadow_uri,
        seed,
        partition_by=[partition_key] if partition_key else None,
        mode="overwrite",
        storage_options=storage_options,
    )


def _run_deltalite_upsert(
    shadow_uri: str,
    storage_options: dict[str, str],
    data: pa.Table,
    primary_keys: Sequence[str],
    partition_key: str | None,
    commit_metadata: dict[str, str] | None,
) -> None:
    table = deltalite.DeltaLiteTable.open(shadow_uri, storage_options)
    table.upsert(
        data,
        list(primary_keys),
        partition_key,
        commit_metadata=commit_metadata,
    )


def _compare(real: pa.Table, shadow: pa.Table, primary_keys: Sequence[str]) -> tuple[bool, dict[str, Any]]:
    """Order-independent logical comparison of two Arrow tables.

    Returns ``(is_match, diagnostics)``. Diagnostics contain only row counts, column sets, and
    *hashes* of diverging primary keys — never row payloads and never raw key values — so nothing
    sensitive is logged.
    """
    real_cols = set(real.column_names)
    shadow_cols = set(shadow.column_names)
    if real_cols != shadow_cols:
        return False, {
            "reason": "schema_mismatch",
            "only_real_cols": sorted(real_cols - shadow_cols),
            "only_shadow_cols": sorted(shadow_cols - real_cols),
        }

    # Compare field *types*, not just names. DuckDB EXCEPT ALL implicitly casts when the two sides
    # differ, so an int32-vs-int64, timestamp-precision, or decimal-scale divergence would otherwise
    # slip through as a false match. Catch it here before the row comparison.
    type_mismatches = {
        name: [str(real.schema.field(name).type), str(shadow.schema.field(name).type)]
        for name in real.column_names
        if not real.schema.field(name).type.equals(shadow.schema.field(name).type)
    }
    if type_mismatches:
        return False, {"reason": "schema_type_mismatch", "type_mismatches": type_mismatches}

    # Align column order (EXCEPT ALL matches by position) to the real table's order.
    shadow = shadow.select(real.column_names)

    con = duckdb.connect()
    try:
        con.register("real_t", real)
        con.register("shadow_t", shadow)
        counts = con.execute(
            """
            SELECT
                (SELECT count(*) FROM real_t),
                (SELECT count(*) FROM shadow_t),
                (SELECT count(*) FROM (SELECT * FROM real_t EXCEPT ALL SELECT * FROM shadow_t)),
                (SELECT count(*) FROM (SELECT * FROM shadow_t EXCEPT ALL SELECT * FROM real_t))
            """
        ).fetchone()
        assert counts is not None  # the aggregate query always returns exactly one row
        real_n, shadow_n, only_real, only_shadow = counts

        if only_real == 0 and only_shadow == 0 and real_n == shadow_n:
            return True, {"rows": real_n}

        pk_cols = ", ".join(f'"{c}"' for c in primary_keys)
        diverging = (
            con.execute(
                f"SELECT {pk_cols} FROM (SELECT * FROM real_t EXCEPT ALL SELECT * FROM shadow_t) LIMIT 20"
            ).fetchall()
            if pk_cols
            else []
        )
        return False, {
            "reason": "content_mismatch",
            "real_rows": real_n,
            "shadow_rows": shadow_n,
            "only_in_real": only_real,
            "only_in_shadow": only_shadow,
            # Keyed HMACs of the diverging rows' primary keys — never the raw values. A warehouse PK can
            # itself be sensitive (e.g. a table keyed by email or a small integer ID); a plain hash of a
            # low-entropy key is trivially reversible by anyone with log access, so the HMAC is keyed with
            # the server secret to defeat enumeration while still letting us count distinct diverging keys
            # and correlate them across runs (the key is stable server-side).
            "diverging_pk_hashes": [_pk_digest(row) for row in diverging],
        }
    finally:
        con.close()


async def run_shadow_comparison(
    *,
    uri: str,
    storage_options: dict[str, str],
    data: pa.Table,
    primary_keys: Sequence[str],
    partition_key: str | None,
    version_before: int,
    version_after: int | None = None,
    commit_metadata: dict[str, str] | None,
    logger: FilteringBoundLogger,
) -> None:
    """Shadow one incremental batch. Best-effort; never raises (all failures become an ``error`` metric).

    Args mirror the merge call site: ``data`` is the already-deduped batch, ``primary_keys`` are the
    normalized PK columns, ``partition_key`` is ``PARTITION_KEY`` when the table is partitioned else
    ``None``, ``version_before`` is the real table's version *before* the merge committed, and
    ``version_after`` is the version the merge produced. The real side is read at ``version_after`` so a
    commit landing between the merge and this read (e.g. a concurrent sync) can't cause a false
    mismatch; ``None`` falls back to latest.
    """
    if not _DELTALITE_AVAILABLE:
        _record("error")
        await logger.adebug("deltalite shadow: deltalite wheel not installed; skipping")
        return

    if random.random() >= settings.DATA_WAREHOUSE_DELTALITE_SHADOW_SAMPLE_RATE:
        _record("skipped")
        return

    if data.num_rows == 0:
        _record("skipped")
        return

    affected = _affected_partition_values(data, partition_key)
    shadow_uri = f"{uri.rstrip('/')}{_SHADOW_SUFFIX}_{random.getrandbits(48):012x}"

    try:
        with DELTALITE_SHADOW_DURATION_SECONDS.time():
            byte_cap = settings.DATA_WAREHOUSE_DELTALITE_SHADOW_MAX_AFFECTED_BYTES
            row_cap = settings.DATA_WAREHOUSE_DELTALITE_SHADOW_MAX_AFFECTED_ROWS
            if (byte_cap and byte_cap > 0) or (row_cap and row_cap > 0):
                stats = await asyncio.to_thread(_affected_at_rest_stats, uri, storage_options, version_before, affected)
                if stats is None:
                    # Fail closed: without a size estimate we can't bound the working set the seed +
                    # comparison will materialize, and the shadow OOMing kills every co-tenant activity
                    # on the pod. A missed sample is free; an OOM is not.
                    _record("skipped")
                    await logger.adebug("deltalite shadow: affected-partition size unknown; skipping (fail closed)")
                    return
                affected_bytes, affected_rows = stats
                if byte_cap and byte_cap > 0 and affected_bytes > byte_cap:
                    _record("skipped")
                    await logger.adebug(
                        f"deltalite shadow: affected partitions {affected_bytes}B over cap {byte_cap}B; skipping"
                    )
                    return
                if row_cap and row_cap > 0 and affected_rows > row_cap:
                    _record("skipped")
                    await logger.adebug(
                        f"deltalite shadow: affected partitions {affected_rows} rows over cap {row_cap}; skipping"
                    )
                    return

            # 1. Seed a throwaway table from the pre-merge state of the affected partitions.
            seed = await asyncio.to_thread(_read_affected, uri, storage_options, version_before, affected)
            await asyncio.to_thread(_seed_shadow, seed, shadow_uri, storage_options, partition_key)

            # 2. Apply the same batch through deltalite.
            try:
                await asyncio.to_thread(
                    _run_deltalite_upsert,
                    shadow_uri,
                    storage_options,
                    data,
                    primary_keys,
                    partition_key,
                    commit_metadata,
                )
            except Exception as e:  # noqa: BLE001 - classify deltalite's typed refusals
                if type(e).__name__ == "DeltaLiteUnsupportedTableError":
                    _record("unsupported")
                    await logger.ainfo(f"deltalite shadow: table not supported by deltalite: {e}")
                    return
                raise

            # 3. Compare against the real (post-merge) result of the affected partitions, pinned to the
            # version the merge produced so a commit landing in between can't fake a mismatch.
            real = await asyncio.to_thread(_read_affected, uri, storage_options, version_after, affected)
            shadow_result = await asyncio.to_thread(_read_affected, shadow_uri, storage_options, None, None)
            is_match, diag = await asyncio.to_thread(_compare, real, shadow_result, primary_keys)

        if is_match:
            _record("match")
            await logger.adebug(f"deltalite shadow: MATCH ({diag.get('rows')} rows)")
        else:
            _record("mismatch")
            # A genuine deltalite correctness bug. Loud, but PII-safe (counts + PK hashes only).
            await logger.aerror(f"deltalite shadow: MISMATCH — {diag}")
    except Exception as e:  # noqa: BLE001 - shadow must never affect the sync
        _record("error")
        await logger.awarning(f"deltalite shadow: errored (ignored, real sync unaffected): {e}")
    finally:
        # Always clean up the throwaway prefix.
        try:
            async with aget_s3_client(fresh_instance=True) as s3:
                await _purge_s3_prefix(s3, shadow_uri)
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            await logger.awarning(f"deltalite shadow: cleanup of {shadow_uri} failed: {e}")
