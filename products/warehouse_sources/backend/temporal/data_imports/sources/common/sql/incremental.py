"""Incremental-field filter contract for SQL sources.

Every SQL source exposes a `filter_<name>_incremental_fields(columns)` helper
that maps the driver's column-type strings onto `IncrementalFieldType`s. The
contract here formalizes what those helpers return and provides a shared
utility to build the `IncrementalField` dicts that `SourceSchema` expects —
removing the identical loop currently copied in every `source.py` façade.
"""

from __future__ import annotations

from typing import Protocol

from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class IncrementalFieldFilter(Protocol):
    """Map driver column tuples onto incremental-capable fields.

    The input tuple is `(name, data_type, nullable)` matching today's
    `filter_<driver>_incremental_fields` signature. The output tuple is
    `(name, IncrementalFieldType, nullable)`.
    """

    def __call__(self, columns: list[tuple[str, str, bool]]) -> list[tuple[str, IncrementalFieldType, bool]]: ...


def build_incremental_fields(
    triples: list[tuple[str, IncrementalFieldType, bool]],
    indexed_columns: set[str] | None = None,
) -> list[IncrementalField]:
    """Convert `(name, type, nullable)` tuples into `IncrementalField` dicts.

    This loop used to live unchanged in every `source.py` (postgres, mysql,
    mssql, snowflake, bigquery, redshift, clickhouse) — centralizing it
    here so schema discovery stays consistent.

    `indexed_columns` is the leading index column set for the table the
    triples came from. `None` means "discovery wasn't run / failed" — the
    UI treats every field as indexed (no warning). When provided, each
    field reports `is_indexed=True` iff its column is the leading column
    of some index.
    """
    return [
        {
            "label": name,
            "type": field_type,
            "field": name,
            "field_type": field_type,
            "nullable": nullable,
            "is_indexed": True if indexed_columns is None else name in indexed_columns,
        }
        for name, field_type, nullable in triples
    ]


def initial_value_for_incremental_type(field_type: IncrementalFieldType) -> object:
    """Thin wrapper around `pipelines.helpers.incremental_type_to_initial_value`.

    Re-exported from this module so callers in `common/sql/` don't have to
    reach into the pipelines package directly (keeps the module graph clean).
    """
    return incremental_type_to_initial_value(field_type)
