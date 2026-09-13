from enum import Enum, StrEnum


class ExperimentMetricType(Enum):
    COUNT = "count"
    CONTINUOUS = "continuous"
    FUNNEL = "funnel"


class PrecomputeSkipReason(StrEnum):
    """Why a metric read never attempted precompute. Tagged on the query as
    `experiment_precompute_skip_reason` and counted per reason by the
    `precompute_overview` staff endpoint, which iterates this enum — a reason
    missing here is invisible in the staff tooling."""

    OVERRIDE_DIRECT = "override_direct"
    TEAM_DISABLED = "team_disabled"
    MIN_RUNTIME = "min_runtime"
    ACTIVATION_CONFIG = "activation_config"
    COHORT_NOT_CALCULATED = "cohort_not_calculated"
    DATA_WAREHOUSE = "data_warehouse"
    GROUP_AGGREGATION = "group_aggregation"
