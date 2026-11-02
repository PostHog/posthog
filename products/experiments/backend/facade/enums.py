"""Exported enums and constants for experiments."""

from decimal import Decimal
from enum import StrEnum

MAX_RECALCULATION_TIMES = 2
# frontend/src/scenes/settings/environment/ExperimentRecalculationTime.tsx repeats this value, so change both together.
MIN_RECALCULATION_GAP_HOURS = 6

# The frequentist engine derives alpha as 1 - confidence level, so anything outside (0, 1) is meaningless. The setting
# stores two decimal places, so these bounds are that open range.
MIN_DEFAULT_CONFIDENCE_LEVEL = Decimal("0.01")
MAX_DEFAULT_CONFIDENCE_LEVEL = Decimal("0.99")


class ExposuresPath(StrEnum):
    """Where a metric query read the exposures. Tagged on the query as `experiment_exposures_path`, and stored with a
    failed metric in `metric_errors`."""

    PRECOMPUTED = "precomputed"
    DIRECT_SCAN = "direct_scan"


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
