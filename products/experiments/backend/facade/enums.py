"""Exported enums and constants for experiments."""

from enum import StrEnum

MAX_RECALCULATION_TIMES = 2
# frontend/src/scenes/settings/environment/ExperimentRecalculationTime.tsx repeats this value, so change both together.
MIN_RECALCULATION_GAP_HOURS = 6


class PrecomputeSkipReason(StrEnum):
    """Why a metric read never attempted precompute. Tagged on the query as
    `experiment_precompute_skip_reason` and counted per reason by the
    `precompute_overview` staff endpoint, which iterates this enum. A reason
    missing here is invisible in the staff tooling."""

    OVERRIDE_DIRECT = "override_direct"
    TEAM_DISABLED = "team_disabled"
    MIN_RUNTIME = "min_runtime"
    ACTIVATION_CONFIG = "activation_config"
    COHORT_NOT_CALCULATED = "cohort_not_calculated"
    DATA_WAREHOUSE = "data_warehouse"
    GROUP_AGGREGATION = "group_aggregation"
