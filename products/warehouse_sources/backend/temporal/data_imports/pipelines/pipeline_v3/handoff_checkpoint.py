from bisect import bisect_left
from itertools import pairwise
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, process_incremental_value
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name


@frozen
class IncrementalBatchRange:
    """The incremental values of one batch whose rows are in ascending order."""

    first: Any
    last: Any
    # The largest value below `last`, or None when every row holds `last`.
    below_last: Any


class IncrementalBatchRangeReader:
    """Reads the `IncrementalBatchRange` of a batch, or None when the batch gives no safe range.

    A batch gives no range when its incremental column is missing, holds a null, or is not in
    ascending order.
    """

    def __init__(self, schema: ExternalDataSchema) -> None:
        self._field_type = schema.incremental_field_type
        self._column_name = normalize_column_name(schema.incremental_field) if schema.incremental_field else None

    def read(self, table: pa.Table) -> IncrementalBatchRange | None:
        if self._column_name is None or self._column_name not in table.column_names:
            return None
        column = table[self._column_name]
        if len(column) == 0 or column.null_count > 0:
            return None
        if self._orders_like_its_processed_values(column.type):
            return self._read_native(column.combine_chunks())
        return self._read_processed([self._process(value) for value in column.to_pylist()])

    @staticmethod
    def _orders_like_its_processed_values(arrow_type: pa.DataType) -> bool:
        # `process_incremental_value` keeps the order of these types. A string can hold a date in
        # any format, so its order is known only after the values are processed.
        return (
            pa.types.is_integer(arrow_type)
            or pa.types.is_floating(arrow_type)
            or pa.types.is_decimal(arrow_type)
            or pa.types.is_timestamp(arrow_type)
            or pa.types.is_date(arrow_type)
        )

    def _process(self, value: Any) -> Any:
        return process_incremental_value(value, self._field_type)

    def _read_native(self, column: pa.Array) -> IncrementalBatchRange | None:
        size = len(column)
        if not pc.all(pc.less_equal(column.slice(0, size - 1), column.slice(1))).as_py():
            return None
        last = column[size - 1]
        rows_below_last = pc.less(column, last).true_count
        return self._range(
            first=self._process(column[0].as_py()),
            last=self._process(last.as_py()),
            below_last=self._process(column[rows_below_last - 1].as_py()) if rows_below_last else None,
        )

    def _read_processed(self, values: list[Any]) -> IncrementalBatchRange | None:
        try:
            if any(value is None for value in values) or not all(a <= b for a, b in pairwise(values)):
                return None
            rows_below_last = bisect_left(values, values[-1])
        except TypeError:
            return None
        return self._range(
            first=values[0], last=values[-1], below_last=values[rows_below_last - 1] if rows_below_last else None
        )

    @staticmethod
    def _range(*, first: Any, last: Any, below_last: Any) -> IncrementalBatchRange | None:
        if first is None or last is None:
            return None
        return IncrementalBatchRange(first=first, last=last, below_last=below_last)


class IncrementalHandoffCheckpoint:
    """Finds the incremental value a later attempt of the same workflow run can resume after.

    Feed it every batch in the order the run stages them. The resume value stays below the newest
    value seen, because rows that share the newest value can still arrive in a later batch and a
    source reads strictly above the value it gets. Rows that arrive out of ascending order void
    the checkpoint: a row that is still to come can then be below a value already given out.
    """

    def __init__(self, resume_value: Any = None) -> None:
        self._resume_value = resume_value
        self._newest: Any = None
        self._void = False

    @property
    def resume_value(self) -> Any:
        return None if self._void else self._resume_value

    @property
    def is_void(self) -> bool:
        return self._void

    def observe(self, batch: IncrementalBatchRange | None) -> None:
        if self._void:
            return
        try:
            if batch is None or (self._newest is not None and batch.first < self._newest):
                self._void = True
                return
            candidate = batch.below_last
            if candidate is None and self._newest is not None and self._newest < batch.last:
                candidate = self._newest
            if candidate is not None and (self._resume_value is None or candidate > self._resume_value):
                self._resume_value = candidate
            self._newest = batch.last
        except TypeError:
            self._void = True
