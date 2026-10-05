"""Replay linkage capability, re-exported for callers outside the experiments product."""

from products.experiments.backend.replay_context import (
    accessible_experiment_ids,
    experiment_prompt_context,
    experiment_status,
    session_attribution,
    session_variant,
    variant_rollout_shares,
)
from products.experiments.backend.replay_linkage import (
    ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES,
    COHORT_NOT_CALCULATED_MESSAGE,
    EXPOSURES_STILL_COMPUTING_MESSAGE,
    IN_SESSION_EVIDENCE_SCAN_MAX_MEMORY_BYTES,
    ExperimentExposureLinkage,
    InSessionExposureSemantics,
    exposed_distinct_ids_select,
    exposed_persons_select,
    exposed_session_ids_select,
    resolve_exposure_linkage,
    resolve_in_session_exposure_semantics,
    targetable_experiments,
    validate_experiment_exposure_access,
)

__all__ = [
    "ACTIVATION_LIVE_SCAN_MAX_MEMORY_BYTES",
    "COHORT_NOT_CALCULATED_MESSAGE",
    "EXPOSURES_STILL_COMPUTING_MESSAGE",
    "IN_SESSION_EVIDENCE_SCAN_MAX_MEMORY_BYTES",
    "ExperimentExposureLinkage",
    "InSessionExposureSemantics",
    "accessible_experiment_ids",
    "experiment_prompt_context",
    "experiment_status",
    "exposed_distinct_ids_select",
    "exposed_persons_select",
    "exposed_session_ids_select",
    "resolve_exposure_linkage",
    "resolve_in_session_exposure_semantics",
    "session_attribution",
    "session_variant",
    "targetable_experiments",
    "validate_experiment_exposure_access",
    "variant_rollout_shares",
]
