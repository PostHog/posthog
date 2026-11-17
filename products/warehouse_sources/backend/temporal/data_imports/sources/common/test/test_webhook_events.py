import datetime

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_event_columns import (
    ARRIVAL_COLUMN,
    EVENT_RANK_COLUMN,
    EVENT_TIME_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_events import latest_event_per_key

_T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
_T1 = _T0 + datetime.timedelta(seconds=1)


class TestLatestEventPerKey:
    @parameterized.expand(
        [
            ("later time wins over later arrival", [("new", _T1, 0, "b"), ("old", _T0, 0, "c")], "new"),
            ("higher rank wins a time tie", [("paid", _T0, 4, "a"), ("open", _T0, 2, "b")], "paid"),
            ("later arrival wins a full tie", [("first", _T0, 0, "a"), ("second", _T0, 0, "b")], "second"),
            ("an event without a time is oldest", [("timed", _T0, 0, "a"), ("untimed", None, 9, "b")], "timed"),
        ]
    )
    def test_newest_event_is_kept(
        self, _name: str, events: list[tuple[str, datetime.datetime | None, int, str]], expected: str
    ) -> None:
        table = pa.table(
            {
                "id": ["k"] * len(events),
                "state": [state for state, *_ in events],
                EVENT_TIME_COLUMN: pa.array([time for _, time, _, _ in events], pa.timestamp("us", tz="UTC")),
                EVENT_RANK_COLUMN: [rank for *_, rank, _ in events],
                ARRIVAL_COLUMN: [arrival for *_, arrival in events],
            }
        )

        assert latest_event_per_key(table, ["id"]).column("state").to_pylist() == [expected]
