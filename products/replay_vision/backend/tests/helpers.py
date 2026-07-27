from typing import Any

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.activities.create_observation import _build_scanner_snapshot


def snapshot_for(scanner: ReplayScanner) -> dict[str, Any]:
    """Build the same `scanner_snapshot` payload that `create_observation_activity` would persist."""
    return _build_scanner_snapshot(scanner)
