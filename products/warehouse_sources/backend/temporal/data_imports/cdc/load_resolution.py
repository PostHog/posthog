"""Resolve a CDC batch against what its table already holds, before the write.

The engine that performs the write replaces whole rows by primary key and accepts no predicates, so
ordering and delete safety have to be settled on the batch rather than in merge clauses.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final

import pyarrow as pa

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    _CDC_METADATA_COLUMNS,
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    CDC_SEQ_PROVENANCE,
)

WRITE_RESOLUTION_FLAG = "dwh-cdc-write-resolution"

# Verification is a diagnostic; cap it so a delete-heavy batch can't dominate the write path.
MAX_VERIFIED_DELETE_ROWS = 1_000
MAX_REPORTED_COLUMNS = 10

# The companion lane. Its table is append-only history, so deduping it would delete versions.
SCD2_APPEND_MODE: Final = "scd2_append"


@frozen
class ResolutionStats:
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


def resolve_batch(
    table: pa.Table,
    primary_keys: list[str],
    *,
    cdc_write_mode: str | None,
) -> tuple[pa.Table, ResolutionStats]:
    """Resolve one lane's batch. Only the consolidated lane dedupes — see SCD2_APPEND_MODE.

    Replay is settled upstream, as the buffer is read: only the reader knows how far into a
    position's rows the last run got, and it reads them in one canonical order.
    """
    duplicates = 0
    if cdc_write_mode != SCD2_APPEND_MODE:
        table, duplicates = dedupe_keep_highest_seq(table, primary_keys)

    return table, ResolutionStats(duplicate_key=duplicates)


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
