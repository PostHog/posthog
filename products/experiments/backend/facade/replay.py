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
    targetable_experiments,
    validate_experiment_exposure_access,
)
from products.experiments.backend.replay_session_coverage import FlagSessionCoverage, resolve_flag_session_coverage

__all__ = [
    "ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES",
    "FlagSessionCoverage",
    "IN_SESSION_EVIDENCE_SCAN_MAX_MEMORY_BYTES",
    "ExperimentExposureLinkage",
    "InSessionExposureSemantics",
    "exposed_distinct_ids_select",
    "exposed_session_ids_select",
    "resolve_exposure_linkage",
    "resolve_flag_session_coverage",
    "resolve_in_session_exposure_semantics",
    "targetable_experiments",
    "validate_experiment_exposure_access",
]
