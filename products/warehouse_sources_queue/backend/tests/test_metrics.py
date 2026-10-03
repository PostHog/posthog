import sys
import math
import asyncio
import subprocess
from pathlib import Path

import pytest

import psycopg
from prometheus_client import CollectorRegistry, multiprocess

from products.warehouse_sources_queue.backend.core.metrics import (
    QUEUE_QUERY_DURATION_SECONDS,
    QUEUE_QUERY_FAILURES_TOTAL,
    observe_queue_query,
)


def _duration_count(query: str) -> float:
    """Total observations for a query label (buckets are stored non-cumulative)."""
    return sum(b.get() for b in QUEUE_QUERY_DURATION_SECONDS.labels(query=query)._buckets)


@pytest.mark.parametrize("process_order", [("holder", "non-holder"), ("non-holder", "holder")])
def test_queue_gauge_multiprocess_collection_preserves_holder_sample(tmp_path, process_order):
    script = """
import os
import sys

os.environ["PROMETHEUS_MULTIPROC_DIR"] = sys.argv[1]

from products.warehouse_sources_queue.backend.core.metrics import (  # noqa: E402
    OLDEST_UNCLAIMED_BATCH_SECONDS,
    clear_queue_sample_gauges,
)

clear_queue_sample_gauges()
if sys.argv[2] == "holder":
    OLDEST_UNCLAIMED_BATCH_SECONDS.set(37)
"""
    repository_root = Path(__file__).resolve().parents[4]
    for process in process_order:
        subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), process],
            check=True,
            cwd=repository_root,
        )

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=str(tmp_path))
    family = next(
        metric for metric in registry.collect() if metric.name == "warehouse_pg_queue_oldest_unclaimed_batch_seconds"
    )
    samples = [sample for sample in family.samples if sample.name == family.name]

    assert len(samples) == 2
    assert all(set(sample.labels) == {"pid"} for sample in samples)
    assert [sample.value for sample in samples if math.isfinite(sample.value)] == [37]
    assert sum(math.isnan(sample.value) for sample in samples) == 1


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
