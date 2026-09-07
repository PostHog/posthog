"""Replay linkage capability, re-exported for callers outside the experiments product."""

from products.experiments.backend.replay_linkage import (
    ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES,
    IN_SESSION_EVIDENCE_SCAN_MAX_MEMORY_BYTES,
    ExperimentExposureLinkage,
    InSessionExposureSemantics,
    exposed_distinct_ids_select,
    exposed_session_ids_select,
    resolve_exposure_linkage,
    resolve_in_session_exposure_semantics,
    validate_experiment_exposure_access,
)

__all__ = [
    "ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES",
    "IN_SESSION_EVIDENCE_SCAN_MAX_MEMORY_BYTES",
    "ExperimentExposureLinkage",
    "InSessionExposureSemantics",
    "exposed_distinct_ids_select",
    "exposed_session_ids_select",
    "resolve_exposure_linkage",
    "resolve_in_session_exposure_semantics",
    "validate_experiment_exposure_access",
]
