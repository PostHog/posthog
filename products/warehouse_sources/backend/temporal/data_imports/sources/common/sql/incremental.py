"""Incremental-field filter contract for SQL sources.

Every SQL source exposes a `filter_<name>_incremental_fields(columns)` helper
that maps the driver's column-type strings onto `IncrementalFieldType`s. The
contract here formalizes what those helpers return and provides a shared
utility to build the `IncrementalField` dicts that `SourceSchema` expects —
removing the identical loop currently copied in every `source.py` façade.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from dateutil import parser as dateutil_parser

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


UNUSABLE_INCREMENTAL_CURSOR_ERROR_PREFIX = "Stored incremental cursor is not a valid"


class UnusableIncrementalCursorError(Exception):
    """Raised when the stored watermark can't be used as a cursor for its field type.

    The watermark lives in the schema's `sync_type_config` and is rendered into the read
    query as a SQL literal. A stale or corrupted value (for example the text NULL marker
    `\\N` that a text-format export leaves behind) makes the source reject the whole
    statement, which is deterministic: every Temporal attempt re-runs the identical query.
    Raising before the query is built turns that into one classified failure with copy the
    customer can act on. `PostgresSource.get_non_retryable_errors` matches the message
    prefix, which excludes the volatile offending value.
    """


def normalize_incremental_field_last_value(last_value: Any, field_type: IncrementalFieldType) -> Any:
    """Return the watermark to render, or the field type's initial value when there is none.

    A missing watermark (`None`, or the empty string a stale `sync_type_config` can hold)
    means the table has never synced, so reading from the initial value is correct.

    A non-empty value that cannot be a value of `field_type` is a different case: the table
    has synced before, so silently restarting from the initial value would re-read it whole
    and duplicate rows on a table with no primary key. Raise instead, so the customer decides
    between a reset and a different incremental field.
    """
    if last_value is None or last_value == "":
        return incremental_type_to_initial_value(field_type)

    # Only text needs checking. Every other stored form is already the matching Python type,
    # which psycopg renders without a cast for the source to reject.
    if not isinstance(last_value, str):
        return last_value

    if not _text_cursor_is_usable(last_value, field_type):
        raise UnusableIncrementalCursorError(
            f"{UNUSABLE_INCREMENTAL_CURSOR_ERROR_PREFIX} {field_type.value} value: {last_value!r}"
        )

    return last_value


def _text_cursor_is_usable(last_value: str, field_type: IncrementalFieldType) -> bool:
    try:
        if field_type in (IncrementalFieldType.Integer, IncrementalFieldType.XID):
            int(last_value)
        elif field_type == IncrementalFieldType.Numeric:
            Decimal(last_value)
        elif field_type in (
            IncrementalFieldType.DateTime,
            IncrementalFieldType.Timestamp,
            IncrementalFieldType.Date,
        ):
            dateutil_parser.parse(last_value)
        else:
            # ObjectID, and any type added later, keep today's behavior: hand the text to the
            # source and let it decide. Adding a check here without knowing the stored forms
            # would risk stopping a sync that works.
            return True
    # `Decimal` raises `decimal.InvalidOperation` (an `ArithmeticError`, which `OverflowError`
    # also derives from); `int` and dateutil raise `ValueError`.
    except (ArithmeticError, ValueError):
        return False

    return True
