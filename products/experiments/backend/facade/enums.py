"""Exported enums and constants for experiments."""

from decimal import Decimal
from enum import StrEnum
from typing import Literal, get_args

from posthog.enums import LabeledStrEnum

MAX_RECALCULATION_TIMES = 2
# frontend/src/scenes/settings/environment/ExperimentRecalculationTime.tsx repeats this value, so change both together.
MIN_RECALCULATION_GAP_HOURS = 6

# The frequentist engine derives alpha as 1 - confidence level, so anything outside (0, 1) is meaningless. The setting
# stores two decimal places, so these bounds are that open range.
MIN_DEFAULT_CONFIDENCE_LEVEL = Decimal("0.01")
MAX_DEFAULT_CONFIDENCE_LEVEL = Decimal("0.99")

LEGACY_METRIC_KINDS: frozenset[str] = frozenset({"ExperimentTrendsQuery", "ExperimentFunnelsQuery"})

# Flag config keys of the deprecated `parameters` surface. The linked flag stores them: a write copies them onto the
# flag and strips them from the column, and a read projects the flag's config back into `parameters`.
FEATURE_FLAG_CONFIG_KEYS: tuple[str, ...] = (
    "feature_flag_variants",
    "rollout_percentage",
    "aggregation_group_type_index",
    "feature_flag_payloads",
    "ensure_experience_continuity",
)


class ExposuresPath(StrEnum):
    """Where a metric query read the exposures. Tagged on the query as `experiment_exposures_path`, and stored with a
    failed metric in `metric_errors`."""

    PRECOMPUTED = "precomputed"
    DIRECT_SCAN = "direct_scan"


# Replaces $feature_flag_called as the default exposure event for experiments that start at or after
# settings.EXPERIMENT_EXPOSURE_EVENT_CUTOFF.
EXPERIMENT_EXPOSURE_EVENT = "$experiment_exposure"

RunningTimeMetricType = Literal["funnel", "mean_count", "mean_sum_or_avg", "ratio", "retention"]
RUNNING_TIME_METRIC_TYPES: tuple[str, ...] = get_args(RunningTimeMetricType)


class MetricSourceRole(StrEnum):
    """What one source node means to its metric, so a hit can say which side of the metric fired."""

    SOURCE = "source"
    STEP = "step"
    NUMERATOR = "numerator"
    DENOMINATOR = "denominator"
    RETENTION_START = "retention_start"
    RETENTION_COMPLETION = "retention_completion"


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
    FLAG_RULE = "flag_rule"


class ExperimentResultConfigurationStatus(LabeledStrEnum):
    CURRENT = "current", "Current settings"
    PREVIOUS = "previous", "Earlier settings"
    UNKNOWN = "unknown", "Settings not recorded"


class SharedMetricType(LabeledStrEnum):
    """The type a shared metric shows in the list. `funnel` and `trend` also cover the legacy query kinds."""

    MEAN = "mean", "Mean"
    FUNNEL = "funnel", "Funnel"
    RATIO = "ratio", "Ratio"
    RETENTION = "retention", "Retention"
    QUANTILE = "quantile", "Percentile"
    TREND = "trend", "Trend"


class RecalculationStartOutcome(StrEnum):
    STARTED = "started"
    # An active run already existed, so no new run was created.
    REUSED = "reused"
    NOT_CREATED = "not_created"
    # The row was created, but the workflow did not start, so the row is marked failed.
    WORKFLOW_NOT_STARTED = "workflow_not_started"


class TerminalMarkOutcome(StrEnum):
    MARKED = "marked"
    NOT_FOUND = "not_found"
    ALREADY_TERMINAL = "already_terminal"
    # A run without a query window never started, so it can only be marked failed.
    NEVER_STARTED = "never_started"
