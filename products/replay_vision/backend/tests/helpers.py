from typing import Any

from prometheus_client import REGISTRY

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.activities.create_observation import _build_scanner_snapshot


def snapshot_for(scanner: ReplayScanner) -> dict[str, Any]:
    """Build the same `scanner_snapshot` payload that `create_observation_activity` would persist."""
    return _build_scanner_snapshot(scanner)


def counter_value(metric_name: str, **labels: str) -> float:
    """Read a Prometheus counter sample by name + labels; treat missing series as 0."""
    return REGISTRY.get_sample_value(metric_name, labels) or 0.0
