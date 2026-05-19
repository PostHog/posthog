import json
import base64
import datetime as dt

import pytest

from products.tracing.backend.presentation.views import _paginate_trace_results


def _row(trace_id: str, ts: dt.datetime, uuid: str) -> dict:
    return {
        "trace_id": trace_id,
        "timestamp": ts,
        "uuid": uuid,
    }


def _decode_cursor(cursor: str) -> dict:
    return json.loads(base64.b64decode(cursor).decode("utf-8"))


class TestPaginateTraceResults:
    def test_empty_results(self):
        kept, has_more, cursor = _paginate_trace_results([], requested_limit=100, order_by="latest")
        assert kept == []
        assert has_more is False
        assert cursor is None

    @pytest.mark.parametrize("order_by", ["latest", "earliest"])
    def test_fewer_traces_than_limit(self, order_by):
        ts = dt.datetime(2026, 1, 1, 12, 0, 0)
        results = [
            _row("trace-a", ts, "uuid-a1"),
            _row("trace-a", ts + dt.timedelta(seconds=1), "uuid-a2"),
            _row("trace-b", ts + dt.timedelta(seconds=2), "uuid-b1"),
        ]
        kept, has_more, cursor = _paginate_trace_results(results, requested_limit=5, order_by=order_by)
        assert kept == results
        assert has_more is False
        assert cursor is None

    @pytest.mark.parametrize("order_by", ["latest", "earliest"])
    def test_exactly_requested_limit_traces(self, order_by):
        ts = dt.datetime(2026, 1, 1, 12, 0, 0)
        results = [
            _row("trace-a", ts, "uuid-a"),
            _row("trace-b", ts + dt.timedelta(seconds=1), "uuid-b"),
            _row("trace-c", ts + dt.timedelta(seconds=2), "uuid-c"),
        ]
        kept, has_more, cursor = _paginate_trace_results(results, requested_limit=3, order_by=order_by)
        assert kept == results
        assert has_more is False
        assert cursor is None

    def test_one_extra_trace_latest_order(self):
        # 3 traces, requested_limit=2 → +1 detected, trace-c dropped.
        # Cursor: trace-b's earliest span (min ts/uuid) for DESC.
        ts = dt.datetime(2026, 1, 1, 12, 0, 0)
        results = [
            _row("trace-a", ts + dt.timedelta(seconds=10), "uuid-a"),
            _row("trace-b", ts + dt.timedelta(seconds=8), "uuid-b1"),
            _row("trace-b", ts + dt.timedelta(seconds=5), "uuid-b2"),
            _row("trace-c", ts + dt.timedelta(seconds=2), "uuid-c"),
        ]
        kept, has_more, cursor = _paginate_trace_results(results, requested_limit=2, order_by="latest")

        assert has_more is True
        assert {row["trace_id"] for row in kept} == {"trace-a", "trace-b"}
        assert cursor is not None

        decoded = _decode_cursor(cursor)
        assert decoded["timestamp"] == (ts + dt.timedelta(seconds=5)).isoformat()
        assert decoded["uuid"] == "uuid-b2"

    def test_one_extra_trace_earliest_order(self):
        # ASC order: cursor is the latest span of last kept trace (trace-b).
        ts = dt.datetime(2026, 1, 1, 12, 0, 0)
        results = [
            _row("trace-a", ts, "uuid-a"),
            _row("trace-b", ts + dt.timedelta(seconds=5), "uuid-b1"),
            _row("trace-b", ts + dt.timedelta(seconds=8), "uuid-b2"),
            _row("trace-c", ts + dt.timedelta(seconds=10), "uuid-c"),
        ]
        kept, has_more, cursor = _paginate_trace_results(results, requested_limit=2, order_by="earliest")

        assert has_more is True
        assert {row["trace_id"] for row in kept} == {"trace-a", "trace-b"}

        decoded = _decode_cursor(cursor)
        assert decoded["timestamp"] == (ts + dt.timedelta(seconds=8)).isoformat()
        assert decoded["uuid"] == "uuid-b2"

    def test_dropped_trace_spans_removed_from_kept(self):
        ts = dt.datetime(2026, 1, 1, 12, 0, 0)
        results = [
            _row("trace-a", ts, "uuid-a"),
            _row("trace-b", ts + dt.timedelta(seconds=1), "uuid-b"),
            _row("trace-c", ts + dt.timedelta(seconds=2), "uuid-c1"),
            _row("trace-c", ts + dt.timedelta(seconds=3), "uuid-c2"),
            _row("trace-c", ts + dt.timedelta(seconds=4), "uuid-c3"),
        ]
        kept, has_more, _ = _paginate_trace_results(results, requested_limit=2, order_by="latest")

        assert has_more is True
        assert len(kept) == 2
        assert all(row["trace_id"] != "trace-c" for row in kept)

    def test_uuid_tiebreaker_on_equal_timestamps(self):
        # When two spans share a timestamp, uuid breaks the tie deterministically.
        ts = dt.datetime(2026, 1, 1, 12, 0, 0)
        results = [
            _row("trace-a", ts, "uuid-a"),
            _row("trace-b", ts + dt.timedelta(seconds=1), "uuid-b1"),
            _row("trace-b", ts + dt.timedelta(seconds=1), "uuid-b2"),
            _row("trace-c", ts + dt.timedelta(seconds=2), "uuid-c"),
        ]
        kept, has_more, cursor = _paginate_trace_results(results, requested_limit=2, order_by="latest")

        assert has_more is True
        decoded = _decode_cursor(cursor)
        # DESC: min by (ts, uuid) → both have same ts, uuid-b1 < uuid-b2 lexically.
        assert decoded["uuid"] == "uuid-b1"
