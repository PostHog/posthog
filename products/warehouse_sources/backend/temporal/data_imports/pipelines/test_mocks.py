"""Shared mock helpers for data-imports pipeline tests (v1 + v3)."""

from __future__ import annotations

from typing import Optional

from unittest.mock import MagicMock

import pyarrow as pa


def mock_delta_table(*, schema_fields: list[pa.Field], partition_columns: Optional[list[str]]) -> MagicMock:
    """Build a mock DeltaTable with controllable schema and metadata().partition_columns.

    Pass `partition_columns=None` to simulate delta-rs returning a missing attribute
    (defensive branch in callers).
    """
    arrow_schema = pa.schema(schema_fields)
    table = MagicMock()
    table.schema = MagicMock(return_value=MagicMock(to_arrow=MagicMock(return_value=arrow_schema)))
    table.metadata = MagicMock(
        return_value=MagicMock(partition_columns=list(partition_columns) if partition_columns is not None else None)
    )
    return table
