"""Tests for the psycopg error translation in `common/sql/errors_psycopg.py`."""

from __future__ import annotations

import pytest

from psycopg.errors import UndefinedColumn

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.errors_psycopg import (
    reader_without_dropped_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    ProjectedColumnMissingError,
)


class TestReaderWithoutDroppedColumns:
    def test_batches_pass_through(self) -> None:
        reader = reader_without_dropped_columns(lambda: iter(["first", "second"]))
        assert list(reader()) == ["first", "second"]

    def test_a_column_dropped_mid_read_is_reraised_clear_of_the_relation_wording(self) -> None:
        def items():
            yield "first"
            raise UndefinedColumn('column "email" does not exist')

        reader = reader_without_dropped_columns(items)
        with pytest.raises(ProjectedColumnMissingError) as raised:
            list(reader())
        # "does not exist" is what the non-retryable rules match on to catch a dropped relation.
        assert "does not exist" not in str(raised.value)
