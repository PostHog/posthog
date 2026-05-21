from typing import Any

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.temporal.activities.create_observation import _build_lens_snapshot


def snapshot_for(lens: ReplayLens) -> dict[str, Any]:
    """Build the same `lens_snapshot` payload that `create_observation_activity` would persist."""
    return _build_lens_snapshot(lens)
