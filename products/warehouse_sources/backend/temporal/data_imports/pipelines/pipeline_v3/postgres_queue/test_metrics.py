import asyncio

import pytest

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.metrics import (
    QUEUE_QUERY_DURATION_SECONDS,
    QUEUE_QUERY_FAILURES_TOTAL,
    observe_queue_query,
)


def _duration_count(query: str) -> float:
    """Total observations for a query label (buckets are stored non-cumulative)."""
    return sum(b.get() for b in QUEUE_QUERY_DURATION_SECONDS.labels(query=query)._buckets)


class TestObserveQueueQuery:
    def test_success_observes_duration(self):
        before = _duration_count("t-success")
        with observe_queue_query("t-success"):
            pass
        assert _duration_count("t-success") == before + 1

    @pytest.mark.parametrize(
        "exc,reason",
        [
            (TimeoutError(), "timeout"),
            (asyncio.CancelledError(), "cancelled"),
            (psycopg.OperationalError(), "db"),
            (ValueError("x"), "other"),
        ],
    )
    def test_failure_still_observes_duration_and_counts_reason(self, exc, reason):
        # The poll histogram's original blind spot: queries that timed out never
        # reached it, so a fleet at its slowest looked fastest. A raise inside
        # the block must land in BOTH the histogram and the failure counter.
        query = f"t-fail-{reason}"
        dur_before = _duration_count(query)
        fail_before = QUEUE_QUERY_FAILURES_TOTAL.labels(query=query, reason=reason)._value.get()

        with pytest.raises(type(exc)):
            with observe_queue_query(query):
                raise exc

        assert _duration_count(query) == dur_before + 1
        assert QUEUE_QUERY_FAILURES_TOTAL.labels(query=query, reason=reason)._value.get() == fail_before + 1
