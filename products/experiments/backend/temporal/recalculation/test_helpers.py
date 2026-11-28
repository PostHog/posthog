"""Helpers shared by the recalculation activity tests."""

from collections.abc import Iterator
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from posthog.schema import PrecomputationMode

from products.experiments.backend.temporal.models import RecalculationProgressUpdate
from products.experiments.backend.temporal.recalculation.calculation import (
    _calculate_experiment_metric_for_recalculation_sync,
)
from products.experiments.backend.temporal.recalculation.discovery import _discover_experiment_metrics_sync
from products.experiments.backend.temporal.recalculation.progress import _update_recalculation_progress_sync

_discover_raw = _discover_experiment_metrics_sync.func  # type: ignore[attr-defined]

_update_raw = _update_recalculation_progress_sync.func  # type: ignore[attr-defined]


def _discover(recalculation_id: str):
    with patch("products.experiments.backend.temporal.recalculation.discovery.close_old_connections"):
        return _discover_raw(recalculation_id)


def _update(update: RecalculationProgressUpdate):
    with patch("products.experiments.backend.temporal.recalculation.progress.close_old_connections"):
        return _update_raw(update)


def _calculate(
    experiment_id: int,
    metric_uuid: str,
    recalculation_id: str,
    query_to: str,
    role: str = "primary",
    is_final_attempt: bool = True,
    attempt: int = 1,
    precomputation_mode: PrecomputationMode | None = None,
    calculation_key_version: int = 1,
    task_queue: str = "",
):
    with patch("products.experiments.backend.temporal.recalculation.calculation.close_old_connections"):
        return _calculate_experiment_metric_for_recalculation_sync(
            experiment_id,
            metric_uuid,
            recalculation_id,
            query_to,
            role,
            is_final_attempt,
            attempt,
            precomputation_mode,
            calculation_key_version,
            task_queue,
        )


@contextmanager
def _patched_runner() -> Iterator[MagicMock]:
    with patch("products.experiments.backend.temporal.recalculation.calculation.ExperimentQueryRunner") as mock_runner:
        # A MagicMock in this attribute can't be stored in `metric_errors`.
        mock_runner.return_value.exposures_path = None
        yield mock_runner


_QUERY_TO = "2026-05-29T12:00:00+00:00"


def _mean_metric(uuid: str) -> dict:
    # ExperimentMeanMetric requires a `source`; a bare {uuid, metric_type} dict fails pydantic validation.
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }


@contextmanager
def _record_captures():
    """Patch the global posthoganalytics client so a test can assert the exact event
    name + properties without sending anything. Yields the list of captured capture(...) kwargs."""
    captured: list[dict] = []

    def _fake_capture(*args, **kwargs) -> None:
        captured.append(kwargs)

    with patch(
        "products.experiments.backend.temporal.recalculation.analytics.posthoganalytics.capture",
        _fake_capture,
    ):
        yield captured
