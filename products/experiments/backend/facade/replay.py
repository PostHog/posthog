"""Replay linkage capability, re-exported for callers outside the experiments product."""

from products.experiments.backend.replay_linkage import (
    ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES,
    ExperimentExposureLinkage,
    exposed_distinct_ids_select,
    resolve_exposure_linkage,
    validate_experiment_exposure_access,
)

__all__ = [
    "ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES",
    "ExperimentExposureLinkage",
    "exposed_distinct_ids_select",
    "resolve_exposure_linkage",
    "validate_experiment_exposure_access",
]
