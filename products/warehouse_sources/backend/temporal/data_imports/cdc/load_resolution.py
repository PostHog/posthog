"""Pre-write resolution of a CDC batch, and verification that DELETE rows kept their data.

Ordering and delete semantics used to be expressed as delta-rs MERGE clauses (predicate-split
`when_matched_update`, plus an `AND source._ph_cdc_seq >= target._ph_cdc_seq` guard). That is no
longer possible: `DeltaWriter.write` routes incremental merges through `deltalite.DeltaLiteTable
.upsert` first and only falls back to the MERGE on failure, and deltalite's upsert has no predicate
surface — it replaces the whole row by primary key. Projecting a DELETE batch down to the tombstone
columns does not help either; deltalite nulls every target column the source omits, which is exactly
the data loss the predicated clause existed to prevent.

So both semantics move here, ahead of the write and independent of which engine performs it:

- ordering is resolved by dropping rows at or below the last committed position, and by deduping to
  the highest position per key, rather than by a merge predicate;
- DELETE rows keep their data because `enrich_delete_rows` filled them, which makes that enrichment
  load-bearing rather than defence in depth — `verify_delete_enrichment` is the detector for when it
  silently fails.

Everything position-related is dormant until batches actually carry `CDC_SEQ_COLUMN` (the legacy
lane strips it), so these helpers no-op on today's traffic.
"""

from __future__ import annotations

import pyarrow as pa

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    _CDC_METADATA_COLUMNS,
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    CDC_SEQ_PROVENANCE,
)

WRITE_RESOLUTION_FLAG = "dwh-cdc-write-resolution"

# Commit-metadata key holding the highest position committed to a table. Read back as the
# watermark for the next batch, so replayed or resurrected buffer files cannot re-apply.
SEQ_WATERMARK_METADATA_KEY = "cdc_max_seq"

# Verification walks DELETE rows in Python. The count is already bounded by the batch, but cap it
# so a pathological delete-only batch cannot dominate the write path.
MAX_VERIFIED_DELETE_ROWS = 1_000

# Enough to identify which columns regressed without unbounded log lines.
MAX_REPORTED_COLUMNS = 10

# The companion (_cdc) lane's write mode. Its table is append-only history, so it is the one lane
# where collapsing to a single row per key would destroy data rather than resolve a conflict.
SCD2_APPEND_MODE = "scd2_append"


@frozen
class ResolutionStats:
    """Rows the resolution step removed, by why."""

    superseded: int
    duplicate_key: int

    def as_pairs(self) -> tuple[tuple[str, int], ...]:
        return (("superseded", self.superseded), ("duplicate_key", self.duplicate_key))


@frozen
class DeleteEnrichmentReport:
    """Outcome of checking that enrichment left DELETE rows with their data values."""

    delete_rows_checked: int
    rows_with_nulled_columns: int
    columns: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.rows_with_nulled_columns == 0


def _data_columns(table: pa.Table, primary_keys: list[str]) -> list[str]:
    pk_set = set(primary_keys)
    return [c for c in table.column_names if c not in _CDC_METADATA_COLUMNS and c not in pk_set]


def _pk_tuples(table: pa.Table, primary_keys: list[str]) -> list[tuple]:
    arrays = [table.column(c).to_pylist() for c in primary_keys]
    return [tuple(a[i] for a in arrays) for i in range(table.num_rows)]


def has_engine_seq(table: pa.Table) -> bool:
    """True only when CDC_SEQ_COLUMN was stamped by the batcher, not supplied by the source.

    A source table may have its own column named `_ph_cdc_seq`; the batcher deliberately passes it
    through untouched rather than overwriting it (collision skip in `_events_to_table`). Name
    presence alone therefore proves nothing, and treating a user value as an engine position would
    let a source set a high number, poison the watermark, and have its own later rows dropped.
    """
    if CDC_SEQ_COLUMN not in table.column_names:
        return False
    field = table.schema.field(CDC_SEQ_COLUMN)
    return (field.metadata or {}).get(b"posthog_cdc") == CDC_SEQ_PROVENANCE[b"posthog_cdc"]


def batch_max_seq(table: pa.Table) -> int | None:
    """Highest engine position in the batch, or None when it carries none."""
    if not has_engine_seq(table) or table.num_rows == 0:
        return None
    values = [v for v in table.column(CDC_SEQ_COLUMN).to_pylist() if v is not None]
    return max(values) if values else None


def drop_superseded_rows(table: pa.Table, watermark: int | None) -> tuple[pa.Table, int]:
    """Drop rows strictly below `watermark` — those are already in the table.

    Rows exactly AT the watermark are kept, which looks redundant but is not: every event in one
    Postgres transaction shares its commit LSN, and a transaction larger than the flush budget is
    split across micro-batches. Dropping `seq == watermark` would silently discard every later
    chunk of a split transaction — real data loss, and invisible. Re-applying rows at the watermark
    is harmless by comparison: the write is an upsert keyed on the primary key, so replaying an
    identical row is a no-op.

    Rows with a null position are kept too: an unknown position cannot be proven stale. No position
    column (today's traffic) or no watermark means no filtering at all.
    """
    if watermark is None or not has_engine_seq(table) or table.num_rows == 0:
        return table, 0

    seqs = table.column(CDC_SEQ_COLUMN).to_pylist()
    keep = [i for i, s in enumerate(seqs) if s is None or s >= watermark]
    if len(keep) == table.num_rows:
        return table, 0
    return table.take(pa.array(keep, type=pa.int64())), table.num_rows - len(keep)


def dedupe_keep_highest_seq(table: pa.Table, primary_keys: list[str]) -> tuple[pa.Table, int]:
    """Collapse each primary key to its highest-position row, preserving batch order otherwise.

    The writer already dedupes keep-last, which is equivalent only while a batch stays ordered by
    position. Buffer files are ordered by construction; this makes the write correct even when that
    stops being true, and deltalite hard-errors on duplicate keys rather than picking one.
    """
    present_pks = [c for c in primary_keys if c in table.column_names]
    if not has_engine_seq(table) or not present_pks or table.num_rows == 0:
        return table, 0

    seqs = table.column(CDC_SEQ_COLUMN).to_pylist()
    keys = _pk_tuples(table, present_pks)

    best: dict[tuple, int] = {}
    for i, key in enumerate(keys):
        current = best.get(key)
        if current is None:
            best[key] = i
            continue
        # Ties and nulls fall back to "later row wins", matching the writer's keep-last dedupe.
        incoming, existing = seqs[i], seqs[current]
        if incoming is None or existing is None or incoming >= existing:
            best[key] = i

    if len(best) == table.num_rows:
        return table, 0
    keep = sorted(best.values())
    return table.take(pa.array(keep, type=pa.int64())), table.num_rows - len(keep)


def resolve_batch(
    table: pa.Table,
    primary_keys: list[str],
    *,
    watermark: int | None,
    cdc_write_mode: str | None,
) -> tuple[pa.Table, ResolutionStats]:
    """Apply position resolution for one lane, before the write.

    Both lanes drop already-applied rows — replaying a buffer file into the companion is how the
    duplicate history rows noted in `cdc/activities.py` arise. Only the consolidated lane dedupes:
    the companion keeps every version of a key on purpose.
    """
    table, superseded = drop_superseded_rows(table, watermark)

    duplicates = 0
    if cdc_write_mode != SCD2_APPEND_MODE:
        table, duplicates = dedupe_keep_highest_seq(table, primary_keys)

    return table, ResolutionStats(superseded=superseded, duplicate_key=duplicates)


def verify_delete_enrichment(
    table: pa.Table,
    primary_keys: list[str],
    existing_rows: pa.Table | None,
) -> DeleteEnrichmentReport:
    """Report DELETE rows that will null a data column the target currently holds.

    Runs after enrichment, against the same `existing_rows` the enrichment consumed, so it costs one
    more pass over rows already materialized. A non-empty report means a delete is about to erase
    data — under deltalite the upsert replaces the row wholesale, so nothing downstream will catch it.
    """
    empty = DeleteEnrichmentReport(delete_rows_checked=0, rows_with_nulled_columns=0, columns=())
    if existing_rows is None or existing_rows.num_rows == 0 or table.num_rows == 0:
        return empty
    if CDC_OP_COLUMN not in table.column_names:
        return empty

    present_pks = [c for c in primary_keys if c in table.column_names and c in existing_rows.column_names]
    if not present_pks:
        return empty

    data_cols = [c for c in _data_columns(table, present_pks) if c in existing_rows.column_names]
    if not data_cols:
        return empty

    existing_by_key: dict[tuple, dict[str, object]] = {}
    existing_keys = _pk_tuples(existing_rows, present_pks)
    existing_values = {c: existing_rows.column(c).to_pylist() for c in data_cols}
    for i, key in enumerate(existing_keys):
        existing_by_key[key] = {c: existing_values[c][i] for c in data_cols}

    ops = table.column(CDC_OP_COLUMN).to_pylist()
    keys = _pk_tuples(table, present_pks)
    outgoing = {c: table.column(c).to_pylist() for c in data_cols}

    checked = 0
    rows_with_nulls = 0
    columns: set[str] = set()
    for i, op in enumerate(ops):
        if op != "D":
            continue
        previous = existing_by_key.get(keys[i])
        if previous is None:
            continue
        if checked >= MAX_VERIFIED_DELETE_ROWS:
            break
        checked += 1
        nulled = [c for c in data_cols if outgoing[c][i] is None and previous[c] is not None]
        if nulled:
            rows_with_nulls += 1
            columns.update(nulled)

    return DeleteEnrichmentReport(
        delete_rows_checked=checked,
        rows_with_nulled_columns=rows_with_nulls,
        columns=tuple(sorted(columns)[:MAX_REPORTED_COLUMNS]),
    )


def is_cdc_write_resolution_enabled(team_id: int, schema_id: str) -> bool:
    """Evaluate the per-team rollout flag for CDC write resolution.

    Fail closed on any error: a flags-service blip must leave today's write path untouched rather
    than silently start dropping rows. Mirrors `is_deltalite_write_enabled`'s property shape so a
    release condition can target one schema before ramping by team.
    """
    import posthoganalytics

    from posthog.models import Team

    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
        return bool(
            posthoganalytics.feature_enabled(
                WRITE_RESOLUTION_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team_id)},
                person_properties={"team_id": str(team_id), "schema_id": str(schema_id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team_id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:  # noqa: BLE001 - a flag-eval or lookup failure means "leave the write path alone"
        return False
