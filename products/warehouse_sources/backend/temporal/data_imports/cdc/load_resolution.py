"""Resolve a CDC batch against what its table already holds, before the write.

The engine that performs the write replaces whole rows by primary key and accepts no predicates, so
ordering and delete safety have to be settled on the batch rather than in merge clauses.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Final

import pyarrow as pa

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    _CDC_METADATA_COLUMNS,
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    CDC_SEQ_PROVENANCE,
)

WRITE_RESOLUTION_FLAG = "dwh-cdc-write-resolution"

# Highest position applied, per lane resource name. Sibling of `cdc_last_log_position`, which
# tracks capture — buffered ingress lets the two diverge, since capture runs ahead of load.
LOAD_POSITION_CONFIG_KEY = "cdc_load_position"
# How many rows of the position above an append lane has already written. A sibling key rather
# than a richer `cdc_load_position`, so a rollback to code that predates it reads the position
# exactly as before instead of finding a shape it cannot parse.
APPLIED_ROWS_CONFIG_KEY = "cdc_load_rows_at_position"

# Verification is a diagnostic; cap it so a delete-heavy batch can't dominate the write path.
MAX_VERIFIED_DELETE_ROWS = 1_000
MAX_REPORTED_COLUMNS = 10

# The companion lane. Its table is append-only history, so deduping it would delete versions.
SCD2_APPEND_MODE: Final = "scd2_append"


@frozen
class ResolutionStats:
    superseded: int
    duplicate_key: int


@frozen
class DeleteEnrichmentReport:
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
    """Whether the position column is ours.

    A source table may have its own `_ph_cdc_seq`, which the batcher passes through untouched, so
    the name proves nothing. Trusting a source value would let it poison the position and have its
    own later rows dropped.
    """
    if CDC_SEQ_COLUMN not in table.column_names:
        return False
    field = table.schema.field(CDC_SEQ_COLUMN)
    return (field.metadata or {}).get(b"posthog_cdc") == CDC_SEQ_PROVENANCE[b"posthog_cdc"]


def batch_max_seq(table: pa.Table) -> int | None:
    if not has_engine_seq(table) or table.num_rows == 0:
        return None
    values = [v for v in table.column(CDC_SEQ_COLUMN).to_pylist() if v is not None]
    return max(values) if values else None


def drop_superseded_rows(table: pa.Table, watermark: int | None) -> tuple[pa.Table, int]:
    """Drop rows strictly below `watermark`.

    Rows exactly at it stay: one Postgres transaction shares a commit LSN across every event, and a
    transaction bigger than the flush budget spans batches, so dropping equality would truncate it.
    Re-applying is cheap by comparison — the write is a primary-key upsert.
    """
    if watermark is None or not has_engine_seq(table) or table.num_rows == 0:
        return table, 0

    seqs = table.column(CDC_SEQ_COLUMN).to_pylist()
    # A null position can't be proven stale, so it survives.
    keep = [i for i, s in enumerate(seqs) if s is None or s >= watermark]
    if len(keep) == table.num_rows:
        return table, 0
    return table.take(pa.array(keep, type=pa.int64())), table.num_rows - len(keep)


def dedupe_keep_highest_seq(table: pa.Table, primary_keys: list[str]) -> tuple[pa.Table, int]:
    """Collapse each primary key to its highest-position row, preserving batch order otherwise.

    deltalite rejects duplicate keys outright, and the writer's keep-last dedupe only matches
    keep-highest while a batch stays ordered by position.
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
        incoming, existing = seqs[i], seqs[current]
        if incoming is None or existing is None or incoming >= existing:  # ties fall back to keep-last
            best[key] = i

    if len(best) == table.num_rows:
        return table, 0
    keep = sorted(best.values())
    return table.take(pa.array(keep, type=pa.int64())), table.num_rows - len(keep)


def _coerce_position(value: Any) -> int | None:
    return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None


def read_load_position(sync_type_config: dict | None, resource_name: str) -> int | None:
    position, _rows = read_load_state(sync_type_config, resource_name)
    return position


def read_load_state(sync_type_config: dict | None, resource_name: str) -> tuple[int | None, int]:
    """This lane's applied position, and how many of its rows AT that position already landed.

    A position alone cannot say how much of its transaction landed — every event of a transaction
    carries the commit's end LSN, so the position repeats across all of them. The count is what
    lets a re-read skip exactly the rows already applied and keep the rest.

    Counting rows rather than naming files is deliberate: a retried capture attempt re-emits the
    same changes under different file names and different batch boundaries (see `buffer.py`), so
    anything keyed on a file would resume at a coordinate that no longer exists. The rows of one
    transaction decode in the same order every time, whatever files they land in.
    """
    config = sync_type_config or {}
    position = _coerce_position((config.get(LOAD_POSITION_CONFIG_KEY) or {}).get(resource_name))
    raw_rows = (config.get(APPLIED_ROWS_CONFIG_KEY) or {}).get(resource_name)
    rows = raw_rows if isinstance(raw_rows, int) and not isinstance(raw_rows, bool) else 0
    return position, max(0, rows)


def provable_position(sync_type_config: dict | None, resource_name: str) -> int | None:
    """The highest position this lane can prove it finished, which is what makes a file deletable.

    A lane part-way through a transaction has NOT finished that transaction's position, and the
    skip that resumes it counts rows across every file the transaction touches. Deleting any of
    them would leave the count pointing past rows the reader can no longer see, and the rows after
    it would be dropped as though they had landed. So a non-zero count proves only the position
    before.
    """
    position, applied_rows = read_load_state(sync_type_config, resource_name)
    if position is None:
        return None
    return position - 1 if applied_rows else position


def persist_load_position(
    schema_id: Any, team_id: int, resource_name: str, position: int, *, rows_at_position: int = 0
) -> None:
    """Record the position and how many rows landed at it — only ever after the commit lands.

    That ordering is the safety argument: these values can then only lag the table, never lead it.
    Lagging re-applies rows, which the upsert makes a no-op and the append lane's skip absorbs;
    leading would skip rows that were never written. The locked merge keeps capture's concurrent
    write to the same JSON column intact.

    Batches of one run land the same position one after another, so a batch at the position already
    recorded ADDS its rows rather than replacing the count — what landed at a transaction is the sum
    across every batch that carried part of it.

    One mutate, because the two values only mean anything together: a position without its count
    reads as a finished transaction and skips nothing, and a count without its position is applied
    against the wrong transaction.
    """
    from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys

    def _merge(config: dict[str, Any]) -> None:
        current_position, current_rows = read_load_state(config, resource_name)
        if current_position is not None and current_position > position:
            return
        rows = current_rows + rows_at_position if current_position == position else rows_at_position
        config.setdefault(LOAD_POSITION_CONFIG_KEY, {})[resource_name] = position
        config.setdefault(APPLIED_ROWS_CONFIG_KEY, {})[resource_name] = rows

    update_sync_type_config_keys(schema_id, team_id, mutate=_merge)


def rows_at_max_seq(table: pa.Table) -> int:
    """How many of this batch's rows sit at its highest position."""
    if not has_engine_seq(table) or table.num_rows == 0:
        return 0
    seqs = [seq for seq in table.column(CDC_SEQ_COLUMN).to_pylist() if seq is not None]
    if not seqs:
        return 0
    top = max(seqs)
    return sum(1 for seq in seqs if seq == top)


def resolve_batch(
    table: pa.Table,
    primary_keys: list[str],
    *,
    watermark: int | None,
    cdc_write_mode: str | None,
) -> tuple[pa.Table, ResolutionStats]:
    """Resolve one lane's batch. Only the consolidated lane dedupes — see SCD2_APPEND_MODE.

    The append lane's replay is settled upstream, as the buffer is read: only the reader knows how
    far into a position's rows the last run got, and it reads them in one canonical order.
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
    """Report DELETE rows that would null a data column the target still holds.

    The upsert replaces whole rows, so an unenriched delete erases data with nothing downstream to
    catch it. Reuses the `existing_rows` enrichment already fetched.
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

    # Narrow before materializing: a wide table would otherwise pull every data column of the whole
    # batch into Python to inspect a capped handful of rows.
    ops = table.column(CDC_OP_COLUMN).to_pylist()
    delete_indices = [i for i, op in enumerate(ops) if op == "D"][:MAX_VERIFIED_DELETE_ROWS]
    if not delete_indices:
        return empty
    deletes = table.take(pa.array(delete_indices, type=pa.int64()))

    existing_keys = _pk_tuples(existing_rows, present_pks)
    existing_values = {c: existing_rows.column(c).to_pylist() for c in data_cols}
    existing_by_key = {key: {c: existing_values[c][i] for c in data_cols} for i, key in enumerate(existing_keys)}

    keys = _pk_tuples(deletes, present_pks)
    outgoing = {c: deletes.column(c).to_pylist() for c in data_cols}

    checked = 0
    rows_with_nulls = 0
    columns: set[str] = set()
    for i in range(deletes.num_rows):
        previous = existing_by_key.get(keys[i])
        if previous is None:
            continue
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


@lru_cache(maxsize=2048)
def is_cdc_write_resolution_enabled(team_id: int, schema_id: str, run_uuid: str) -> bool:
    """Per-team rollout gate, resolved once per schema per run.

    Keyed on `run_uuid` to keep a flags round trip off every batch's write path. Fails closed: a
    flags blip must not start dropping rows.
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
    except Exception:  # noqa: BLE001
        return False
