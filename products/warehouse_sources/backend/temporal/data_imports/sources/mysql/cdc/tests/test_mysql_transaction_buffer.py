import decimal
import datetime as dt

from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc import transaction_buffer
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.transaction_buffer import (
    TransactionBuffer,
)

_COMMITTED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _event(row_id: int) -> ChangeEvent:
    return ChangeEvent(
        operation="I",
        table_name="app.orders",
        position_serialized="",
        timestamp=dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
        columns={"id": row_id, "amount": decimal.Decimal("1.50"), "raw": b"\x00\x01"},
    )


class TestTransactionBuffer:
    @parameterized.expand([("in_memory", 100), ("spilled_whole_chunks", 2), ("spilled_with_a_tail", 3)])
    def test_commit_returns_every_change_in_order_at_the_commit_position(self, _name, chunk):
        buffer = TransactionBuffer()
        with patch.object(transaction_buffer, "SPILL_CHUNK_EVENTS", chunk):
            for row_id in range(6):
                buffer.add(_event(row_id))
            committed = list(buffer.commit("0@binlog.000001:900", _COMMITTED_AT))

        assert [event.columns for event in committed] == [_event(row_id).columns for row_id in range(6)]
        assert {(event.position_serialized, event.timestamp) for event in committed} == {
            ("0@binlog.000001:900", _COMMITTED_AT)
        }
        assert len(buffer) == 0
        assert list(buffer.commit("0@binlog.000001:950", _COMMITTED_AT)) == []
