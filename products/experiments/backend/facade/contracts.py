"""
Facade contracts (DTOs) for experiments product.

These are framework-free frozen dataclasses that define the interface
between the experiments product and the rest of the system.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Generic, Literal, Optional, TypeVar

from pydantic import JsonValue

from posthog.hogql.property_access_types import RestrictedProperty

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

from products.experiments.backend.facade.enums import MetricSourceRole, RecalculationStartOutcome, SharedMetricType

if TYPE_CHECKING:
    from uuid import UUID

    from posthog.schema import MaxExperimentSummaryContext

# Metrics per section (primary/secondary) included in the AI results summary
MAX_METRICS_TO_SUMMARIZE = 50


@frozen
class StoredArmResult:
    key: str
    number_of_samples: int
    mean: float | None
    change: float | None = None
    significant: bool | None = None


@frozen
class StoredPrimaryResult:
    """The current stored result of an experiment's primary metric."""

    metric_name: str
    metric_type: str | None
    proportion: bool
    goal: str | None
    baseline: StoredArmResult
    variants: tuple[StoredArmResult, ...]


@frozen
class ExperimentUnfurlVariant:
    """One variant of the experiment's flag and its share of the rollout."""

    key: str
    # As the flag stores it, so a whole number stays an int and prints as `50`, not `50.0`.
    rollout_percentage: float


@frozen
class ExperimentUnfurl:
    """What a link preview shows for an experiment."""

    id: int
    # An object access check reads the creator. The preview does not show it.
    created_by_id: int | None
    name: str
    description: str | None
    # Public status string: draft, running, paused, exposure_frozen, or stopped.
    status: str
    start_date: datetime | None
    end_date: datetime | None
    updated_at: datetime
    # The name of the first inline primary metric, when that metric has one.
    primary_metric_name: str | None
    # The variants of the experiment's flag, in the flag's order. Empty when the flag config can't be read.
    variants: tuple[ExperimentUnfurlVariant, ...]


@frozen
class ExperimentSummaryData:
    """Result of fetching experiment data for the AI results summary."""

    context: "MaxExperimentSummaryContext"
    last_refresh: datetime | None
    pending_calculation: bool
    omitted_metric_count: int


@frozen
class ExperimentResultsWidgetMetric:
    """One metric of the dashboard experiment results widget."""

    uuid: str | None
    name: str
    # The metric that the query ran, as JSON. None when the metric has no result.
    metric: dict[str, Any] | None
    # The query response as JSON, without the SQL and the per-variant session payloads.
    result: dict[str, Any] | None
    # A message that is safe to show to the viewer. None when the metric has a result.
    error: str | None


@frozen
class ExperimentResultsWidgetMetrics:
    """The metrics of a launched experiment, per section, in display order."""

    primary: tuple[ExperimentResultsWidgetMetric, ...]
    secondary: tuple[ExperimentResultsWidgetMetric, ...]
    # The metric count of each section. Only the first metrics of a section run, so a total can be larger than the
    # metrics above.
    primary_total: int
    secondary_total: int


@frozen
class ExperimentResultsWidget:
    """One experiment, as the dashboard experiment results widget shows it."""

    id: int
    name: str
    # Public status string: draft, running, paused, exposure_frozen, or stopped.
    status: str
    start_date: datetime | None
    end_date: datetime | None
    feature_flag_key: str
    # None for a draft, which has no exposures to compute results from.
    metrics: ExperimentResultsWidgetMetrics | None


@frozen
class TargetableExperiment:
    """A launched experiment whose exposed sessions a replay surface can narrow to."""

    id: int
    name: str
    description: str
    # The variant keys a caller may ask for, excluded variants already removed.
    variants: tuple[str, ...]


@frozen
class ExperimentVariantPromptContext:
    """One variant, as an LLM prompt describes it."""

    key: str
    # The flag variant's display name, which the experiment UI treats as the variant's description.
    description: str
    rollout_percentage: float


@frozen
class ExperimentPromptContext:
    """What an LLM prompt needs to describe an experiment and the change under test."""

    id: int
    name: str
    # The experiment's description field, which carries the hypothesis and expected outcomes.
    description: str
    feature_flag_key: str
    # Requestable variants only, excluded variants already removed.
    variants: tuple[ExperimentVariantPromptContext, ...]
    primary_metric_names: tuple[str, ...]


@frozen
class ExperimentFlagVariantSplit:
    """One variant of the experiment's flag and its share of the rollout, as the flag stores them."""

    # None when the stored variant has no key.
    key: str | None
    # As stored, so a whole number stays an int and a prompt prints `50%`, not `50.0%`. 0 when the variant has none.
    rollout_percentage: float


@frozen
class ExperimentAssistantContext:
    """What PostHog AI reads to describe an experiment and its results."""

    id: int
    # With `id`, the fields that an object access check reads.
    team_id: int
    created_by_id: int | None
    name: str
    description: str | None
    type: str | None
    start_date: datetime | None
    end_date: datetime | None
    created_at: datetime
    conclusion: str | None
    conclusion_comment: str | None
    stats_method: Literal["bayesian", "frequentist"]
    # Variant names by key from the experiment's own variants field, which web experiments write. A variant without a
    # name maps to its key.
    variant_names: Mapping[str, str]
    feature_flag_key: str
    # Every variant of the flag, in the flag's order. Excluded variants are not removed.
    feature_flag_variants: tuple[ExperimentFlagVariantSplit, ...]


@frozen
class SessionAttribution:
    """One person's attribution in an experiment's exposed population, as the analysis buckets it."""

    variant: str
    # The person's earliest exposure in the experiment window. A session that ended before this
    # predates the exposure, so surfaces comparing variants must not count it.
    first_exposure_time: datetime | None


@frozen
class ExperimentStatus:
    """The lifecycle facts a replay surface reads to decide whether an experiment is still worth watching."""

    # Public status string: draft, running, paused, exposure_frozen, or stopped.
    status: str
    start_date: datetime | None
    end_date: datetime | None
    archived: bool
    # The running-time calculator's recommended length in days, when one was set.
    planned_duration_days: float | None

    @property
    def is_active(self) -> bool:
        """True until the experiment ends or is archived. A paused experiment (its flag turned
        off) stays active: it collects no exposures while paused, but it resumes without a
        lifecycle change, so a watcher should keep watching."""
        return self.start_date is not None and self.end_date is None and not self.archived


class ExperimentHealthFindingCode(LabeledStrEnum):
    # pinned: the page sends these values as `finding_code` on the health finding events
    # (products/experiments/frontend/health/experimentHealthFindingEvents.ts), and insights group on them.
    FLAG_OFF_WHILE_RUNNING = "flag_off_while_running"
    VARIANT_SHIPPED_WHILE_RUNNING = "variant_shipped_while_running"
    FLAG_LIVE_AFTER_END = "flag_live_after_end"
    FLAG_LIVE_BEFORE_LAUNCH = "flag_live_before_launch"
    BIAS_RISK_MULTIPLE_EXCLUDED = "bias_risk_multiple_excluded"
    MULTIPLE_VARIANTS_SHARE = "multiple_variants_share"
    NO_METRIC = "no_metric"
    METRIC_EVENT_NOT_INGESTED = "metric_event_not_ingested"
    METRIC_USES_FEATURE_FLAG_CALLED = "metric_uses_feature_flag_called"
    METRIC_CANNOT_COMPILE = "metric_cannot_compile"
    METRIC_CALCULATION_FAILED = "metric_calculation_failed"
    METRIC_ALL_ZERO = "metric_all_zero"
    EXPOSURE_CRITERIA_CANNOT_MATCH = "exposure_criteria_cannot_match"
    EXPOSURE_FILTER_ON_DYNAMIC_COHORT = "exposure_filter_on_dynamic_cohort"
    SRM = "srm", "Sample Ratio Mismatch"
    ZERO_EXPOSURES = "zero_exposures"
    TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES = "test_account_filter_removes_exposures"
    UNSERVED_VARIANT_EXPOSURES = "unserved_variant_exposures"
    EVENTS_BILLING_LIMIT = "events_billing_limit"
    FEATURE_FLAGS_BILLING_LIMIT = "feature_flags_billing_limit"
    FORCED_VARIANT_RELEASE_CONDITION = "forced_variant_release_condition"
    FLAG_VARIANTS_MISMATCH = "flag_variants_mismatch"
    SPLIT_CHANGED_MID_RUN = "split_changed_mid_run"
    BUCKETING_CHANGED_MID_RUN = "bucketing_changed_mid_run"
    RELEASE_CONDITIONS_CHANGED_MID_RUN = "release_conditions_changed_mid_run"
    NEW_FLAG_NO_TRAFFIC = "new_flag_no_traffic"
    EARLY_SIGNIFICANCE = "early_significance"
    METRICS_NOT_MATURED = "metrics_not_matured"
    RESULT_READY = "result_ready"
    FLAG_SHARED = "flag_shared"
    STALE_EXPERIMENT = "stale_experiment"
    EXPOSURE_ROWS_LEFT_OUT = "exposure_rows_left_out"


class ExperimentHealthMetricCompileErrorKind(LabeledStrEnum):
    # A validation error of the query builder, written for the user.
    REJECTED = "rejected"
    # HogQL can't parse an expression of the metric.
    SYNTAX = "syntax"
    # HogQL can't compile the query.
    QUERY = "query"
    # The stored definition doesn't parse into a metric.
    DEFINITION = "definition"


class ExperimentHealthFlagChangeKind(LabeledStrEnum):
    SPLIT = "split"
    # A setting that decides the variant draw: the key, the group type, the bucketing identifier or persistence.
    BUCKETING = "bucketing"
    RELEASE_CONDITIONS = "release_conditions", "Release-condition"


class ExperimentHealthFindingSeverity(LabeledStrEnum):
    # The values are the severities of the platform's health issues (posthog/models/health_issue.py), so a
    # finding can become a health issue by value. The labels differ on purpose: two choice sets with the same
    # values and labels share one OpenAPI enum, and the generated name of the other one would change.
    CRITICAL = "critical", "Critical severity"
    WARNING = "warning", "Warning severity"
    INFO = "info", "Info severity"


class ExperimentHealthFindingActionKind(LabeledStrEnum):
    OPEN_FEATURE_FLAG = "open_feature_flag"
    OPEN_FEATURE_FLAG_HISTORY = "open_feature_flag_history"
    ADJUST_DISTRIBUTION = "adjust_distribution"
    USE_FIRST_SEEN_VARIANT = "use_first_seen_variant"
    ADD_PRIMARY_METRIC = "add_primary_metric"
    ADD_SECONDARY_METRIC = "add_secondary_metric"
    EDIT_EXPOSURE_CRITERIA = "edit_exposure_criteria"
    EDIT_RELEASE_CONDITIONS = "edit_release_conditions"
    END_EXPERIMENT = "end_experiment"
    FREEZE_EXPOSURE = "freeze_exposure"
    MOVE_START_DATE = "move_start_date"


class ExperimentHealthCheckKey(LabeledStrEnum):
    # pinned: the health endpoint and the exposure query return these values, so API callers depend on them. A key
    # names the check, not a problem: `flag_state` reports four finding codes, and `flag_history` reports its finding
    # under `split_changed_mid_run`.
    FLAG_STATE = "flag_state"
    FLAG_SHARED = "flag_shared"
    FLAG_HISTORY = "flag_history"
    SPLIT_CHANGED_MID_RUN = "split_changed_mid_run"
    BUCKETING_CHANGED_MID_RUN = "bucketing_changed_mid_run"
    RELEASE_CONDITIONS_CHANGED_MID_RUN = "release_conditions_changed_mid_run"
    FLAG_VARIANTS_MISMATCH = "flag_variants_mismatch"
    FORCED_VARIANT_RELEASE_CONDITION = "forced_variant_release_condition"
    NEW_FLAG_NO_TRAFFIC = "new_flag_no_traffic"
    NO_METRIC = "no_metric"
    METRIC_EVENT_NOT_INGESTED = "metric_event_not_ingested"
    METRIC_USES_FEATURE_FLAG_CALLED = "metric_uses_feature_flag_called"
    METRIC_CANNOT_COMPILE = "metric_cannot_compile"
    METRIC_CALCULATION_FAILED = "metric_calculation_failed"
    METRIC_ALL_ZERO = "metric_all_zero"
    EXPOSURE_CRITERIA_CANNOT_MATCH = "exposure_criteria_cannot_match"
    EXPOSURE_FILTERS = "exposure_filters"
    EARLY_SIGNIFICANCE = "early_significance"
    METRICS_NOT_MATURED = "metrics_not_matured"
    RESULT_READY = "result_ready"
    STALE_EXPERIMENT = "stale_experiment"
    ZERO_EXPOSURES = "zero_exposures"
    TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES = "test_account_filter_removes_exposures"
    SRM = "srm"
    UNSERVED_VARIANT_EXPOSURES = "unserved_variant_exposures"
    BIAS_RISK_MULTIPLE_EXCLUDED = "bias_risk_multiple_excluded"
    MULTIPLE_VARIANTS_SHARE = "multiple_variants_share"
    EVENTS_BILLING_LIMIT = "events_billing_limit"
    FEATURE_FLAGS_BILLING_LIMIT = "feature_flags_billing_limit"
    EXPOSURE_ROWS_LEFT_OUT = "exposure_rows_left_out"


@frozen
class ExperimentHealthFinding:
    """One problem that a health check found in an experiment, with what fixes it."""

    code: ExperimentHealthFindingCode
    subcode: str | None
    # pinned: the page sends it as `finding_reason` on the health finding events. Never customer text.
    reason: str | None = None
    severity: ExperimentHealthFindingSeverity
    title: str
    detail: str
    evidence: Mapping[str, str | int | float | bool | None]
    actions: tuple[ExperimentHealthFindingActionKind, ...]
    diagnostic_ref: str | None
    # The check that reported the finding. A code doesn't name its check, because one check can report several codes.
    # The registry sets it, so a check leaves it out.
    check: ExperimentHealthCheckKey | None = None


class ExperimentHealthCheckStatus(LabeledStrEnum):
    PASSED = "passed"
    FINDING = "finding"
    NOT_APPLICABLE = "not_applicable"
    # The check covers the experiment, but it could not read an input or it failed, so a problem can go unreported.
    NOT_CHECKED = "not_checked"


class ExperimentHealthValueKey(LabeledStrEnum):
    # API callers read these keys in a check's `values` and its `rule`. The suffix gives the unit: `_count` is a
    # count, `_percentage` is on the 0-100 scale, `_hours` is hours and `_at` is an ISO 8601 time in UTC. A key without a
    # unit suffix is a setting or a state, as a string or a boolean, and in a row also an object. A key means the same
    # thing in every check, so two values that differ in meaning get two keys.
    EXPOSED_COUNT = (
        "exposed_count",
        "Users or groups exposed since launch, as the exposure criteria count them, including those exposed to "
        "multiple variants",
    )
    COMPARED_COUNT = (
        "compared_count",
        "Exposed users or groups in the variants that the sample ratio test compares, without those exposed to "
        "multiple variants",
    )
    MULTIPLE_VARIANT_COUNT = "multiple_variant_count", "Users or groups exposed to more than one variant"
    MULTIPLE_VARIANT_PERCENTAGE = "multiple_variant_percentage", "multiple_variant_count as a share of exposed_count"
    MULTIPLE_VARIANT_HANDLING = (
        "multiple_variant_handling",
        "What the results do with users exposed to more than one variant: exclude or first_seen",
    )
    P_VALUE = "p_value", "P-value of the sample ratio test"
    SINCE_LAUNCH_HOURS = "since_launch_hours", "Hours since launch"
    EXPOSED_WITHOUT_TEST_ACCOUNT_FILTER_COUNT = (
        "exposed_without_test_account_filter_count",
        "Users or groups that the exposure criteria count without the test account filters",
    )
    KEPT_BY_TEST_ACCOUNT_FILTER_PERCENTAGE = (
        "kept_by_test_account_filter_percentage",
        "exposed_count as a share of exposed_without_test_account_filter_count",
    )
    UNSERVED_EXPOSED_COUNT = (
        "unserved_exposed_count",
        "Users or groups first exposed after the day of the feature flag's last save, in a variant that the flag "
        "doesn't serve since that save",
    )
    UNSERVED_EXPOSED_PERCENTAGE = (
        "unserved_exposed_percentage",
        "unserved_exposed_count as a share of the users or groups first exposed after that day",
    )
    ONLY_COUNT_MATURED_USERS = (
        "only_count_matured_users",
        'Whether "Require completed conversion or retention window" is on',
    )
    PRIMARY_METRIC_COUNT = "primary_metric_count", "Primary metrics of the experiment"
    SECONDARY_METRIC_COUNT = "secondary_metric_count", "Secondary metrics of the experiment"
    WAITING_METRIC_COUNT = (
        "waiting_metric_count",
        "Of the primary metrics, those whose conversion or retention window hasn't passed for any user yet",
    )
    METRIC_COUNT = "metric_count", "Metrics that the calculation computes"
    COMPLETED_METRIC_COUNT = "completed_metric_count", "Metrics whose result of the latest calculation the page shows"
    FAILED_METRIC_COUNT = "failed_metric_count", "Metrics whose latest calculation failed"
    CALCULATED_AT = "calculated_at", "When the latest calculation of the metrics finished"
    FLAG_ACTIVE = "flag_active", "Whether the feature flag is enabled"
    FLAG_DELETED = "flag_deleted", "Whether the feature flag is deleted"
    FLAG_ROLLED_OUT = "flag_rolled_out", "Whether a release condition of the feature flag rolls out to more than 0%"
    SHIPPED_VARIANT = (
        "shipped_variant",
        "The key of the variant that the feature flag serves to everyone, or null when it serves more than one",
    )
    FLAG_LAST_CALLED_AT = "flag_last_called_at", "When PostHog last recorded a call of the feature flag"
    FLAG_CALLED = "flag_called", "Whether PostHog has recorded a call of the feature flag"
    SINCE_START_HOURS = (
        "since_start_hours",
        "Hours since the experiment's start date, which can be earlier than the launch",
    )
    DAILY_CALCULATION_ENDS_AT = (
        "daily_calculation_ends_at",
        "When the daily calculation stops covering the experiment, a fixed number of days after its start date",
    )
    EVENTS_BILLING_LIMIT_REACHED = (
        "events_billing_limit_reached",
        "Whether the organization reached its billing limit for product analytics, so that PostHog drops the "
        "project's product analytics events",
    )
    EVENTS_BILLING_LIMIT_ENDS_AT = (
        "events_billing_limit_ends_at",
        "When PostHog stops dropping the project's product analytics events, unless the limit lifts earlier",
    )
    FEATURE_FLAGS_BILLING_LIMIT_REACHED = (
        "feature_flags_billing_limit_reached",
        "Whether the organization reached its billing limit for feature flags, so that PostHog returns no flags to "
        "the project's flag requests",
    )
    FEATURE_FLAGS_BILLING_LIMIT_ENDS_AT = (
        "feature_flags_billing_limit_ends_at",
        "When PostHog returns flags to the project's flag requests again, unless the limit lifts earlier",
    )
    METRIC_NAME = "metric_name", "The name of a metric"
    METRIC_ROLE = "metric_role", "Whether a metric is primary or secondary"
    RATIO_SIDE = (
        "ratio_side",
        "The side of a ratio metric, numerator or denominator, or null for the other metric types",
    )
    SAMPLE_COUNT = "sample_count", "Users or groups in a metric's results, across the variants"
    PLANNED_SAMPLE_COUNT = (
        "planned_sample_count",
        "Users or groups that the running time estimate needs to detect its minimum detectable effect",
    )
    DATA_HOURS = (
        "data_hours",
        "Hours of data that a metric's latest calculation holds since launch, within the metric's conversion window",
    )
    VARIANT = "variant", "The key of a variant"
    DIFFERENCE_PERCENTAGE = (
        "difference_percentage",
        "A variant's difference from the control on the primary metric, relative to the control, with its sign",
    )
    DETECTABLE_DIFFERENCE_PERCENTAGE = (
        "detectable_difference_percentage",
        "The smallest difference from the control that the variant's sample can reliably detect, relative to the "
        "control",
    )
    SIGNIFICANT = "significant", "Whether a variant's difference from the control is significant"
    SIGNIFICANT_SINCE_AT = (
        "significant_since_at",
        "Since when every result of the primary metric, up to the current one, shows a variant as significant. With "
        "more than one significant variant, the earliest date",
    )
    FORCED_CONDITION_COUNT = (
        "forced_condition_count",
        "Release conditions of the feature flag that serve a fixed variant through a variant override",
    )
    MATCHED_COUNT = (
        "matched_count",
        "Users or groups that a release condition served since traffic_since_at, without those forced to a variant "
        "that has 0% in the split",
    )
    VARIANT_MATCHED_COUNT = (
        "variant_matched_count",
        "Of matched_count, the users or groups who got the variant. Estimated from the split for those assigned at "
        "random",
    )
    FORCED_COUNT = "forced_count", "Users or groups that a release condition with a variant override served"
    FORCED_PERCENTAGE = "forced_percentage", "forced_count as a share of variant_matched_count"
    TRAFFIC_SINCE_AT = (
        "traffic_since_at",
        "The start of the window that matched_count counts: 7 days ago, or the launch or the flag's last save if later",
    )
    HISTORY_SINCE_AT = (
        "history_since_at",
        "The start of the feature flag's history that the check reads: the experiment's start date, which can be "
        "earlier than the launch",
    )
    CHANGE_COUNT = (
        "change_count",
        "Changes of the feature flag since history_since_at of the kind that the check looks for, such as split "
        "changes",
    )
    CHANGED_AT = "changed_at", "When a change of the feature flag was saved"
    BEFORE_EXPOSURE = (
        "before_exposure",
        "Whether a change of the feature flag was saved before anyone was exposed, so it moved nobody. Null when "
        "unknown",
    )
    CHANGED_SETTING = (
        "changed_setting",
        "The flag setting that a change of the bucketing changed, as the flag page names it",
    )
    BEFORE = "before", "What a change of the feature flag changed, as it was before the change, in words"
    AFTER = "after", "What a change of the feature flag changed, as it was after the change, in words"
    BEFORE_FILTERS = (
        "before_filters",
        "The feature flag's release conditions before a change, as the flag stores them: an object with the groups "
        "and the aggregation_group_type_index of its filters. Null when they don't fit the size limit of the check's "
        "rows. The flag's history shows them in full",
    )
    AFTER_FILTERS = (
        "after_filters",
        "The feature flag's release conditions after a change, as the flag stores them, like before_filters",
    )
    FLAG_SERVICE_CALL_PERCENTAGE = (
        "flag_service_call_percentage",
        "Of the feature flag's calls since traffic_since_at that returned a variant, the share that the flag service "
        "evaluated. Only these calls name the release condition that served them, so local evaluation and bootstrapped "
        "values count in no condition",
    )
    COHORT_COUNT = "cohort_count", "Cohorts that the exposure criteria filter on"
    DYNAMIC_COHORT_COUNT = (
        "dynamic_cohort_count",
        "Of cohort_count, the dynamic cohorts, whose members the results read at the time of the calculation",
    )
    EVENT = "event", "The name of an event that the check looked up"
    EVENT_RECEIVED = (
        "event_received",
        "Whether the project has received the event. Null when PostHog keeps no record of the event name",
    )
    INVALID_METRIC_COUNT = "invalid_metric_count", "Metrics whose query doesn't compile, so every calculation fails"
    UNCHECKED_METRIC_COUNT = (
        "unchecked_metric_count",
        "Metrics whose query the check couldn't compile, because they read data that the reader can't query or the "
        "compile failed for a reason other than the metric",
    )
    FLAG_SPLIT = "flag_split", "The feature flag's variants with their rollout percentages, in words"
    BASELINE_VARIANT = (
        "baseline_variant",
        "The key of the variant that the analysis compares the others with, or null when the analysis picks one",
    )
    OTHER_RUNNING_EXPERIMENT_COUNT = (
        "other_running_experiment_count",
        "Other experiments that run on the same feature flag and are not archived",
    )
    ASSIGNED_OUTSIDE_COUNT = (
        "assigned_outside_count",
        "Users or groups who got a variant from a call that the flag service didn't evaluate and that is no local "
        "evaluation, such as a bootstrapped value. Read only while a running experiment's feature flag has a 0% rollout",
    )
    OTHER_DRAFT_EXPERIMENT_COUNT = (
        "other_draft_experiment_count",
        "Other draft experiments on the same feature flag that are not archived",
    )
    FILTERS_TEST_ACCOUNTS = (
        "filters_test_accounts",
        "Whether the counts leave out internal and test users, because the experiment applies the test account filters",
    )
    LEFT_OUT_ROW_COUNT = (
        "left_out_row_count",
        "Rows of the warehouse-native exposure query that the exposures leave out, for any reason",
    )
    UNKNOWN_VARIANT_ROW_COUNT = (
        "unknown_variant_row_count",
        "Rows of the warehouse-native exposure query whose variant is none of the experiment's variants",
    )
    EMPTY_ID_ROW_COUNT = (
        "empty_id_row_count",
        "Rows of the warehouse-native exposure query whose entity_id is empty",
    )


ExperimentHealthValue = str | int | float | bool | None
ExperimentHealthRowValue = ExperimentHealthValue | Mapping[str, object]


class ExperimentHealthRuleSide(LabeledStrEnum):
    ABOVE = "above", "Finding above the threshold"
    BELOW = "below", "Finding below the threshold"


class ExperimentHealthRuleTest(LabeledStrEnum):
    CHI_SQUARED = "chi_squared", "Chi-squared goodness-of-fit test"


@frozen
class ExperimentHealthRuleMinimum:
    """What a check needs before it judges: below the threshold, it doesn't report a finding."""

    value: ExperimentHealthValueKey
    threshold: float


@frozen
class ExperimentHealthCheckRule:
    """How a check decides, as data. It is the same for every experiment, so the values of a run say how close the
    check is to a finding."""

    value: ExperimentHealthValueKey
    threshold: float
    # The side of the threshold that reports a finding. A value at the threshold doesn't.
    warns: ExperimentHealthRuleSide
    test: ExperimentHealthRuleTest | None = None
    minimum: ExperimentHealthRuleMinimum | None = None


@frozen
class ExperimentHealthCheckResult:
    key: ExperimentHealthCheckKey
    name: str
    description: str
    status: ExperimentHealthCheckStatus
    # Why the check did not look, for the statuses not_applicable and not_checked. None otherwise.
    reason: str | None
    # What the check read on the experiment, for every status. Empty when it read nothing or shows nothing.
    values: Mapping[ExperimentHealthValueKey, ExperimentHealthValue]
    rule: ExperimentHealthCheckRule | None
    # What the check read per variant, metric or flag change, with the same keys as `values`.
    rows: tuple[Mapping[ExperimentHealthValueKey, ExperimentHealthRowValue], ...]


@frozen
class ExperimentHealthReleaseCondition:
    """A condition set of the flag: the share of its matching users or groups who get the flag, how many filters they
    must match, the group type it assigns variants by (None for users), and the variant it serves to all of them (None
    when the split picks one)."""

    rollout_percentage: float
    property_count: int
    aggregation_group_type_index: int | None
    variant: str | None
    # False when the set serves nobody: its rollout is 0%, or an earlier set ends the flag's evaluation before it.
    # None on a flag that buckets by device ID, because a request without a device ID skips the earlier sets that need
    # the bucketing hash and can reach the set anyway.
    reachable: bool | None


@frozen
class ExperimentHealthExposureSetup:
    """What the exposure criteria count as an exposure. Neither an event nor an action means the flag's calls."""

    event: str | None
    action: str | None
    # The event, or the action's name, that has to follow a user's flag call before the user counts.
    activation: str | None


class ExperimentHealthStatsMethod(LabeledStrEnum):
    BAYESIAN = "bayesian", "Bayesian"
    FREQUENTIST = "frequentist", "Frequentist"


class ExperimentHealthMultipleVariantHandling(LabeledStrEnum):
    EXCLUDE = "exclude", "Exclude from analysis"
    FIRST_SEEN = "first_seen", "Use first seen variant"


@frozen
class ExperimentHealthAnalysisSetup:
    """What the results calculation reads besides the metrics, resolved as the calculation resolves it. A
    `*_from_project_default` field is true when the experiment doesn't set the value, so the calculation takes the
    project's default."""

    stats_method: ExperimentHealthStatsMethod
    confidence_level: float
    sequential_testing: bool | None
    sequential_testing_from_project_default: bool
    cuped: bool
    cuped_lookback_days: int | None
    cuped_from_project_default: bool
    cuped_lookback_days_from_project_default: bool
    # The names of the calculated metrics whose type CUPED doesn't support. Empty when CUPED is off.
    metrics_without_cuped_support: tuple[str, ...]
    filters_test_accounts: bool | None
    test_account_filter_count: int
    multiple_variant_handling: ExperimentHealthMultipleVariantHandling | None
    only_count_matured_users: bool
    baseline_variant: str
    excluded_variants: tuple[str, ...]


@frozen
class ExperimentHealthSetup:
    """The settings of the experiment and its flag that decide who gets the flag, which variant a user gets, who counts
    as exposed, and how the results are calculated."""

    # The flag's condition sets as stored, in evaluation order.
    release_conditions: tuple[ExperimentHealthReleaseCondition, ...]
    early_exit: bool
    bucketing_identifier: str
    aggregation_group_type_index: int | None
    evaluation_runtime: str
    evaluation_contexts: tuple[str, ...]
    ensure_experience_continuity: bool
    # None when the exposure criteria can't be read, or the exposures come from a data warehouse table.
    exposure: ExperimentHealthExposureSetup | None
    analysis: ExperimentHealthAnalysisSetup


@frozen
class ExperimentHealth:
    findings: tuple[ExperimentHealthFinding, ...]
    checks: tuple[ExperimentHealthCheckResult, ...]
    # None when not loaded or when the experiment has no flag. Only the health endpoint loads it.
    setup: ExperimentHealthSetup | None = None


@frozen
class ExperimentHealthReaderAccess:
    """What the caller of the health checks may read, for the checks that read more than the experiment."""

    can_read_flag_history: bool
    can_query_events: bool
    denied_event_properties: frozenset[str]
    # The reader's property access rules. A query that a check runs without the reader runs under them.
    restricted_properties: frozenset[RestrictedProperty]


class ExperimentValidationError(Exception):
    """Raised when the facade refuses an experiment write for its input. The message is written for the person who
    sent the input, so a caller at an HTTP boundary can return it as a 400."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        # The input field that the message is about, so that an HTTP boundary can report the error on that field.
        # None when the message is about the input as a whole.
        self.field = field


class ExperimentVersionConflict(Exception):
    """Raised when a stale write raced a concurrent update and could not be applied safely. The detail is written for
    the person who sent the write, so a caller at an HTTP boundary can return it as a 409."""

    def __init__(
        self,
        detail: str = "This experiment changed since you loaded it. Review the latest changes and try again.",
        *,
        current_version: int,
        conflicting_fields: list[str] | None = None,
        conflicting_metric_uuids: list[str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.current_version = current_version
        self.conflicting_fields = conflicting_fields or []
        self.conflicting_metric_uuids = conflicting_metric_uuids or []


class LegacyMigrationError(Exception):
    """Raised when a legacy experiment can't move onto the new engine. The message is written for the person who asked
    for the migration."""


@frozen
class InSessionExposureSemantics:
    """How the in-session narrowing reads on one experiment.

    One resolution serves both the recordings query's refusal and the tab's scope control, so the
    two can't drift: the control disables exactly what the query would refuse, and the copy can say
    when the evidence is the stamped-property stand-in rather than the exposure event itself.
    """

    # Why in-session narrowing can't answer for this experiment. None when it can.
    unavailable_reason: str | None
    # True when the evidence is the stamped `$feature/<key>` property: it means the flag was active in the session,
    # not that the exposure event was captured there.
    uses_stamped_fallback: bool

    @property
    def available(self) -> bool:
        """True when a query carrying the narrowing would be accepted."""
        return self.unavailable_reason is None


@frozen
class ExperimentExposureLinkage:
    """A validated experiment-exposure filter, resolved to how its population will be read.

    Obtained from `facade.replay.resolve_exposure_linkage` and handed back to the replay facade's
    select builders and `session_attribution`, so a query built later reads the same resolution.
    """

    # The variants the population covers: the caller's narrowing without duplicates, or every requestable variant when
    # the caller asked for none.
    requested_variants: tuple[str, ...]
    # max_memory_usage ceiling the synchronous recordings-list run must apply when the live
    # scan needs explicit bounding instead of relying on cluster defaults. It bounds the whole
    # embedding query, so a kill renders as the platform's generic memory-limit error rather
    # than anything exposure-specific. Composition callers that execute the linkage's AST
    # through their own async or batch pipelines run under those pipelines' limits and may
    # ignore it.
    live_scan_max_memory_bytes: int | None
    # True when the exposure criteria apply the team's test-account filters, so the exposed
    # population is already test-filtered at the person level. Queries that restrict their rows
    # to this population can skip re-applying the same filters to their own rows.
    population_filters_test_accounts: bool
    # True when the linkage narrows to sessions with in-session exposure evidence.
    in_session: bool
    # The product's resolution, which only the replay facade reads back. It holds the query context, so it is typed
    # `object` to keep that context off the contract. It is left out of equality and hashing.
    _resolution: object = field(compare=False, repr=False)


# Hard cap on the batch endpoint's id list. A playlist page holds 20 recordings, and every
# extra session widens the grouped scans; anything larger should arrive as separate batches.
MAX_SESSION_CONTEXT_BATCH = 20


@frozen
class SessionMetricSourceHit:
    """One source of a metric with at least one matching event in a session."""

    role: MetricSourceRole
    name: str
    # Position among *all* the metric's sources, data-warehouse ones included, so a funnel step
    # keeps its real step number even when an earlier step has no session events.
    index: int
    total: int
    event_count: int
    first_timestamp: datetime
    timestamps: tuple[datetime, ...]


@frozen
class SessionMetricHit:
    """A metric with at least one matching event in a session."""

    metric_uuid: str
    metric_name: str
    event_count: int
    first_timestamp: datetime
    # The first event timestamps, ascending: seek points for the player. event_count is the true
    # total, so this can be shorter than event_count.
    timestamps: tuple[datetime, ...]
    # Which of the metric's sources fired, so a hit reads as "step 2 of 3" or "the start event of
    # a retention metric" rather than an unqualified "this metric happened". Sources with no
    # matching event are omitted, as is the whole breakdown when the metric is over the
    # aggregate-group ceiling.
    sources: tuple[SessionMetricSourceHit, ...]


@frozen
class SessionExperiment:
    """One experiment whose feature flag a session recording saw, and what the session saw of it."""

    experiment_id: int
    experiment_name: str
    flag_key: str
    variant: str
    variants_seen: tuple[str, ...]
    multiple_variants: bool
    first_exposure_timestamp: datetime | None
    experiment_start_date: datetime | None
    experiment_end_date: datetime | None
    # The experiment's metrics with >=1 matching event in the session, sorted by first occurrence.
    metrics_in_session: tuple[SessionMetricHit, ...]


# Ceiling on returned session ids. The recordings list is fetched over GET, so the ids ride in a
# query string: ~45 encoded characters each puts 100 ids at ~4.5 KB, with headroom under the 8 KB
# request-line limits proxies commonly enforce. Doubling it would not.
MAX_SESSION_BUCKET_LIMIT = 100
# The scan reads every session in the window, not a known id list, so the window is what bounds
# it. It ends at the latest in-session exposure rather than at now, because an experiment whose
# exposures stopped has nothing left in its recent days. The response carries the window it read,
# because a clamped scan has to state what it left out.
MAX_BUCKET_SCAN_DAYS = 30


# The labels repeat the values because the published OpenAPI enum lists these exact pairs.
class ExperimentSessionBucket(LabeledStrEnum):
    """Which question the returned session set answers."""

    FIRED_ANY = "fired_any", "fired_any"
    NO_METRIC_ACTIVITY = "no_metric_activity", "no_metric_activity"
    FUNNEL_DROPOFF = "funnel_dropoff", "funnel_dropoff"


class SessionBucketUnavailable(Exception):
    """The requested bucket can't be computed for this experiment — a caller error, not a
    failure. Raised instead of returning an empty session list, so an unmatchable metric never
    reads as "no sessions matched"."""


@dataclass(frozen=True)
class BucketMetric:
    metric_uuid: str
    metric_name: str


@dataclass(frozen=True)
class ExcludedBucketMetric:
    metric_uuid: str
    metric_name: str
    reason: str


@dataclass(frozen=True)
class SessionBucketScan:
    """What the scan found, and what gets cached: every recorded match, most recent first, not yet
    cut to `limit`.

    The cut waits for the viewer's per-recording access filter, which runs on read so a revocation
    lands even on a warm entry. Cutting first would let a denied recording spend a returned slot,
    and would let `truncated` carry the one bit that a recording the viewer can't see matched.
    """

    candidate_session_ids: list[str]
    # The scan filled its over-fetch batch, so more matches may exist beyond the ones it saw.
    scan_hit_cap: bool
    limit: int
    considered_metrics: list[BucketMetric]
    excluded_metrics: list[ExcludedBucketMetric]
    date_from: datetime
    date_to: datetime
    filter_test_accounts: bool
    used_exposure_fallback: bool


@dataclass(frozen=True)
class SessionBucketResult:
    """One viewer's answer: the sessions they may see, cut to the limit."""

    session_ids: list[str]
    truncated: bool
    considered_metrics: list[BucketMetric]
    excluded_metrics: list[ExcludedBucketMetric]
    date_from: datetime
    date_to: datetime
    filter_test_accounts: bool
    used_exposure_fallback: bool


EXPERIMENT_BEHAVIOR_COMPARISON_FLAG = "experiment-behavior-comparison"
# The most days of events one comparison reads. Tighter than MAX_BUCKET_SCAN_DAYS. The bucket scan
# filters by event name in its WHERE, so ClickHouse prunes on the events table's primary key; this
# one compares every event name there is and has no such predicate, so time is all that stands
# between it and the team's whole history.
MAX_DELTA_SCAN_DAYS = 14
# How far past a person's first exposure their events are read. Their compared session is the one
# holding their earliest event in this stretch, so the bound keeps "first session after exposure"
# meaning the session where they met the change, and it caps the per-(person, session) aggregation
# state for people with many sessions. Stretches are clamped at the window end, so a person first
# exposed inside the horizon of an experiment's end date is read over what is left of it: still
# the session they met the change in, with only its tail missing.
FIRST_SESSION_HORIZON_HOURS = 24
# How many recordings a card names to start with. Enough to offer a choice, few enough that the
# reader still opens one instead of reading a second list.
MAX_CARD_HIGHLIGHTS = 3
MAX_CARD_RECORDINGS = 20


class SessionEventDeltasUnavailable(Exception):
    """The cards can't be computed for this experiment — a caller error, not a failure.
    Raised instead of returning an empty shelf, so "we declined to compare" never reads as
    "the variants behaved identically"."""


# The labels repeat the values because the published OpenAPI enum lists these exact pairs.
class ExperimentWatchCardStrength(LabeledStrEnum):
    """How far apart a variant and the rest are, conservatively, in bands rather than as a number."""

    # Nobody in the other variants did it, among the people compared. A fact about the compared set
    # rather than a ratio, and the one band that is exact.
    ONLY = "only", "only"
    FAR_MORE = "far_more", "far_more"
    MORE = "more", "more"
    SLIGHTLY_MORE = "slightly_more", "slightly_more"


# The labels repeat the values because the published OpenAPI enum lists these exact pairs.
class ExperimentWatchCardKind(LabeledStrEnum):
    # An event this variant did clearly more than the other variants together.
    BEHAVIOR = "behavior", "behavior"
    # Same evidence, but the event is an error/rage signal, so it reads as a defect lead.
    FRICTION = "friction", "friction"
    # An event only this variant can fire, because the variant is what renders it. Confirms the change is
    # live rather than saying anything about what people did with it.
    VARIANT_ONLY = "variant_only", "variant_only"
    # A shortcut to recordings around one of the experiment's own metric events. No comparison
    # claim: what happened to the metric is the results tab's answer.
    METRIC = "metric", "metric"


# The labels repeat the values because the published OpenAPI enum lists these exact pairs.
class ExperimentWatchEmptyReason(LabeledStrEnum):
    """Why a shelf carries no cards. Set exactly when the shelf is empty.

    Each reason asks something different of the reader, so the frontend and the MCP tool report
    the reason rather than an empty list.
    """

    # Fewer than two variants cleared MIN_VARIANT_PERSONS. A rollout split that changed during the
    # run lands here too, undiagnosed, because the exposure chart already shows it.
    TOO_EARLY = "too_early", "too_early"
    # The variants were compared and no event told them apart.
    NO_SEPARATION = "no_separation", "no_separation"
    # Events told the variants apart, but no recording behind them can be opened.
    NO_RECORDINGS = "no_recordings", "no_recordings"
    # The experiment has exposed people and none of them has a session the scan can see in the
    # window. Only the sessions are read over the window; who counts as exposed is read over the
    # whole run, so the exposures can predate the window, which is why the copy must date the claim
    # to the window rather than to the exposures. More time alone cannot fix it: more traffic
    # captured the same way produces more exposed people without sessions. The read stops at the
    # request, though, so people exposed less than a horizon ago can still return, and the copy
    # must not claim the day has passed.
    NO_SESSION_LINKED_EXPOSURES = "no_session_linked_exposures", "no_session_linked_exposures"


@dataclass(frozen=True)
class ExperimentWatchHighlight:
    """One recording a card names first, and everything it carries that earned it the place.

    The friction signals are session-level rather than per event, so a recording keeps them on
    every card it backs. That is deliberate: the reason has to survive a reader opening the
    recording, and "this session rage clicked six times" does, while anything scoped to the card's
    own event would contradict itself the moment the same session appeared under a second card.
    The one per-card part, "did this N times", survives the same trip because "this" reads against
    whichever card it is printed on.
    """

    session_id: str
    reason: str


@dataclass(frozen=True)
class ExperimentWatchCard:
    """One group of recordings worth opening, and the one sentence that justifies it.

    Deliberately no rate, no ratio and no person count: a precise number next to an event name is
    an effect size, and the results tab publishes those for everything the experiment measures,
    computed over a different window and a different unit. The only number here is how many
    recordings the card can actually show.
    """

    kind: ExperimentWatchCardKind
    event: str
    # The variant whose recordings these are — for comparison cards, the variant that did the event more.
    variant: str
    # None on metric cards: they are shortcuts, not comparisons.
    strength: Optional[ExperimentWatchCardStrength]
    # The metric this card's event belongs to, on a shortcut card and on a comparison card alike.
    # Set means the results tab measures this event, so the card must be read as pointing there
    # rather than as a second answer.
    metric_name: Optional[str]
    recording_count: int
    session_ids: list[str]
    # Which of those recordings to open first, strongest signal first. Empty when none of them
    # carries one, which is itself worth showing: it says the card's recordings are unremarkable
    # apart from the event that earned the card.
    highlights: list[ExperimentWatchHighlight]


@dataclass(frozen=True)
class ExperimentWatchVariant:
    """One variant's compared population: exposed people, and the sessions they were seen in."""

    key: str
    persons: int
    sessions: int


@dataclass(frozen=True)
class ExperimentWatchResult:
    cards: list[ExperimentWatchCard]
    variants: list[ExperimentWatchVariant]
    multiple_variant_persons: int
    multiple_variant_handling: str
    metric_events: list[str]
    date_from: datetime
    date_to: datetime
    filter_test_accounts: bool
    # Always False. The population is person-scoped now, so no stamped-property stand-in exists to
    # fall back to; the field stays so the payload shape holds for existing readers.
    used_exposure_fallback: bool
    # True when more people were exposed than one comparison covers, so the most recently exposed
    # were compared. Named for the session ceiling it used to report, kept so the payload shape
    # holds for existing readers.
    sessions_truncated: bool
    events_truncated: bool
    min_variant_persons: int
    # Reported so a reader can tell a card carrying every recording of its event from one that ran
    # into the ceiling. A count sitting on the cap is a floor, and printed as a plain number beside
    # an event name it reads as a measurement of that event.
    max_card_recordings: int
    # How many cards the duplicate-recording-set rule removed from this viewer's shelf, reported
    # so the shelf-loaded telemetry can say how often DUPLICATE_CARD_OVERLAP fires on real shelves
    # before anyone tunes it. Set in `finalize_watch_cards` rather than in the scan, because the
    # shelf is cached across viewers and the duplicate cut runs on the shelf a viewer actually gets.
    dropped_duplicate_cards: int
    too_early: bool
    # Settled per viewer in `finalize_watch_cards`: the recording access cut can empty a shelf the
    # scan built with findings on it.
    empty_reason: Optional[ExperimentWatchEmptyReason]


EXPERIMENT_SETUP_CONTEXT_FLAG: Final = "experiment-setup-context"
DEFAULT_LIST_LIMIT: Final = 10
MAX_LIST_LIMIT: Final = 25
MAX_PROPERTY_FILTERS: Final = 10


class SetupContextSectionStatus(LabeledStrEnum):
    OK = "ok"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ERROR = "error"


class SdkLibCategory(LabeledStrEnum):
    WEB = "web"
    MOBILE = "mobile"
    SERVER = "server"
    OTHER = "other"


class PreviousExperimentState(LabeledStrEnum):
    """Every value `Experiment.status_label` can return, which is what this section reports."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    EXPOSURE_FROZEN = "exposure_frozen"
    STOPPED = "stopped"


@frozen
class SetupContextInputs:
    target_event: str | None = None
    target_url_contains: str | None = None
    # Tuples so the frozen dataclass carries no shared mutable default.
    target_properties: tuple[dict[str, Any], ...] = ()
    metric_event: str | None = None
    metric_properties: tuple[dict[str, Any], ...] = ()
    previous_experiments_limit: int = DEFAULT_LIST_LIMIT
    shared_metrics_limit: int = DEFAULT_LIST_LIMIT

    def __post_init__(self) -> None:
        if self.target_url_contains and self.target_event != "$pageview":
            raise ValueError("target_url_contains needs target_event to be $pageview")
        if self.target_properties and not self.target_event:
            raise ValueError("target_properties needs target_event")
        if self.metric_properties and not self.metric_event:
            raise ValueError("metric_properties needs metric_event")
        for filters in (self.target_properties, self.metric_properties):
            if len(filters) > MAX_PROPERTY_FILTERS:
                raise ValueError(f"pass at most {MAX_PROPERTY_FILTERS} property filters")
        # The same event on both sides makes every person who reached the surface a converter, so
        # the baseline would always be 1.0 and tell the caller nothing.
        if self.metric_event and self.metric_event == self.target_event:
            raise ValueError("metric_event must differ from target_event")
        for limit in (self.previous_experiments_limit, self.shared_metrics_limit):
            if not 1 <= limit <= MAX_LIST_LIMIT:
                raise ValueError(f"list limits must be between 1 and {MAX_LIST_LIMIT}")


@frozen
class TeamDefaults:
    stats_method: str | None
    confidence_level: float | None
    minimum_detectable_effect: int | None
    product_default_minimum_detectable_effect: int
    product_default_stats_method: str
    product_default_confidence_level: float
    only_count_matured_users: bool
    cuped_enabled: bool
    sequential_testing_enabled: bool
    flags_persistence_default: bool
    test_account_filter_count: int
    new_experiments_filter_test_accounts: bool
    default_exposure_event: str


@frozen
class SdkLibProfile:
    lib: str | None
    category: SdkLibCategory
    calls: int
    distinct_ids: int
    device_id_share: float
    # None when no call from this SDK carried the property at all, so a 0 is never mistaken for a
    # fact. Derived from what the rows carry rather than from the SDK's name, because the name
    # lists are incomplete and each SDK decides for itself what it sends.
    locally_evaluated_share: float | None
    anonymous_share: float | None


@frozen
class LibActivity:
    lib: str | None
    category: SdkLibCategory
    events: int
    distinct_ids: int


@frozen
class SdkProfile:
    window_days: int
    source_event: str
    computed_at: datetime
    libs: list[SdkLibProfile]
    libs_truncated: bool
    flags_seen: int
    flags_evaluated_on_server_and_web: int
    evaluated_on_server_and_web: bool
    libs_on_any_event: list[LibActivity] | None
    libs_on_any_event_truncated: bool


@frozen
class LibReach:
    lib: str | None
    category: SdkLibCategory
    unique_persons: int
    anonymous_share: float | None
    device_id_share: float


@frozen
class TargetSurface:
    window_days: int
    source_event: str
    target_url_contains: str | None
    target_properties: list[dict[str, Any]]
    computed_at: datetime
    test_accounts_filtered: bool
    unique_persons: int
    exposures_per_day_estimate: float
    libs: list[LibReach]
    libs_truncated: bool
    anonymous_share: float | None
    device_id_share: float | None


@frozen
class FunnelBaselineStats:
    number_of_samples: int
    # The calculator's input contract requires `sum` on every baseline, so the funnel carries it too.
    sum: float
    step_counts: list[float]


@frozen
class MeanCountBaselineStats:
    number_of_samples: int
    sum: float
    sum_squares: float


@frozen
class CandidateMetric:
    window_days: int
    source_event: str
    metric_properties: list[dict[str, Any]]
    target_event: str | None
    computed_at: datetime
    test_accounts_filtered: bool
    persons_reached: int | None = None
    persons_converted: int | None = None
    conversion_rate: float | None = None
    funnel_baseline_stats: FunnelBaselineStats | None = None
    mean_count_baseline_stats: MeanCountBaselineStats | None = None
    note: str | None = None
    event_volume: int | None = None
    unique_persons: int | None = None


@frozen
class ExperimentOutcome:
    metric_type: str
    # None when the stored result carries no sample counts at all, which must not read as a zero:
    # "the experiment analyzed nobody" is the signal this section exists to surface.
    metric_samples: int | None
    analyzed_exposures: int | None
    control_baseline_value: float | None
    any_variant_significant: bool
    result_completed_at: datetime | None
    result_data_through: datetime | None


@frozen
class PreviousExperiment:
    id: int
    name: str
    state: PreviousExperimentState
    created_at: datetime
    start_date: datetime | None
    end_date: datetime | None
    conclusion: str | None
    feature_flag_key: str
    variant_count: int
    split_even: bool | None
    serving_single_variant: str | None
    rollout_percentage: float | None
    multiple_variant_handling: str
    multiple_variant_handling_set: bool
    ensure_experience_continuity: bool
    bucketing_identifier: str
    evaluation_runtime: str
    group_aggregation: bool
    custom_exposure_event: str | None
    custom_exposure_action_id: int | None
    exposure_property_filters: list[dict[str, Any]]
    activation_event: str | None
    activation_action_id: int | None
    filter_test_accounts: bool
    primary_metric_count: int
    secondary_metric_count: int
    shared_metric_count: int
    primary_metric_types: list[str]
    primary_metric_events: list[str]
    primary_metric_action_ids: list[int]
    minimum_detectable_effect: float | None
    stats_method: str
    has_holdout: bool
    outcome: ExperimentOutcome | None


@frozen
class PreviousExperimentsSummary:
    total: int
    launched: int
    launched_without_results: int
    launched_with_unknown_analyzed_exposures: int
    launched_with_zero_analyzed_exposures: int
    launched_with_under_100_analyzed_exposures: int
    using_device_id_bucketing: int
    using_persistence: int
    using_custom_exposure: int
    using_exposure_property_filters: int
    using_activation: int
    using_uneven_split: int
    serving_single_variant: int


@frozen
class PreviousExperiments:
    experiments: list[PreviousExperiment]
    summary: PreviousExperimentsSummary


@frozen
class SharedMetricUsage:
    id: int
    name: str
    metric_type: str | None
    events: list[str]
    action_ids: list[int]
    used_as_primary: int
    used_as_secondary: int
    last_used_at: datetime | None
    matches_metric_event: bool | None
    metric_event_roles: list[str] | None


@frozen
class SharedMetrics:
    metric_event: str | None
    metric_event_match_truncated: bool
    metrics: list[SharedMetricUsage]


# hoglint reads an unbound type variable as an unknown type, so the bound is what lets the facade hand a section out.
SetupContextSectionData = (
    TeamDefaults | SdkProfile | TargetSurface | CandidateMetric | PreviousExperiments | SharedMetrics
)
_SectionData = TypeVar("_SectionData", bound=SetupContextSectionData)


@frozen
class SetupContextSection(Generic[_SectionData]):
    status: SetupContextSectionStatus
    data: _SectionData | None = None


@frozen
class ExperimentSetupContext:
    team_defaults: SetupContextSection[TeamDefaults]
    sdk_profile: SetupContextSection[SdkProfile]
    target_surface: SetupContextSection[TargetSurface]
    candidate_metric: SetupContextSection[CandidateMetric]
    previous_experiments: SetupContextSection[PreviousExperiments]
    shared_metrics: SetupContextSection[SharedMetrics]


@dataclass(frozen=True)
class CreateExperimentInput:
    """
    Input for creating an experiment.

    Note: This class is NOT hashable when dict/list fields are non-None due to
    mutable types. Use only immutable fields if hashability is required.
    """

    # Required fields
    name: str
    feature_flag_key: str

    # Optional basic fields
    description: str = ""
    type: str = "product"

    # Experiment-own parameters (variant_notes, custom_exposure_filter, prompt_metadata, ...).
    # Flag config is NOT accepted here — it goes through feature_flag_config below.
    parameters: dict[str, Any] | None = None

    # Feature flag configuration in the flag's own write shape:
    # {filters: {multivariate, groups, aggregation_group_type_index, payloads}, ensure_experience_continuity}
    feature_flag_config: dict[str, Any] | None = None

    # Running-time calculator state (minimum_detectable_effect, recommended_running_time,
    # recommended_sample_size, exposure_estimate_config)
    running_time_calculation: dict[str, Any] | None = None

    # Variant keys dropped from statistical analysis
    excluded_variants: list[str] | None = None

    # Metrics configuration
    metrics: list[dict] | None = None
    metrics_secondary: list[dict] | None = None
    secondary_metrics: list[dict] | None = None
    metrics_ordering: tuple[str, ...] | None = None  # primary_metrics_ordered_uuids
    secondary_metrics_ordering: tuple[str, ...] | None = None  # secondary_metrics_ordered_uuids
    saved_metrics_ids: list[dict] | None = None

    # Statistics and exposure configuration
    stats_config: dict | None = None
    exposure_criteria: dict | None = None
    only_count_matured_users: bool | None = None

    # Experiment lifecycle
    start_date: datetime | None = None
    end_date: datetime | None = None
    archived: bool = False
    deleted: bool = False
    conclusion: str | None = None
    conclusion_comment: str | None = None
    # GitHub repo (`org/repo`) targeted by the flag-cleanup PR on experiment end
    repository: str | None = None

    # Advanced configuration
    holdout_id: int | None = None  # We'll pass ID, facade will load the model
    filters: dict | None = None
    scheduling_config: dict | None = None
    create_in_folder: str | None = None
    # The experiment rule to link when feature_flag_key names an existing flag with rules.
    feature_flag_rule_id: "UUID | None" = None

    # Internal flags
    allow_unknown_events: bool = False
    serializer_context: dict | None = None


@dataclass(frozen=True)
class FeatureFlag:
    """Feature flag output."""

    id: int
    key: str
    active: bool
    created_at: datetime
    name: str | None = None


@frozen
class ExperimentCreator:
    """The user who created an experiment, with the fields that core's `UserBasicSerializer` renders. A caller
    serializes it through that serializer, so the response keeps the `UserBasic` shape."""

    id: int
    uuid: "UUID"
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    # The stored value. `UserBasicSerializer` shapes it when it renders.
    hedgehog_config: dict[str, Any] | None
    role_at_organization: str | None


@frozen
class ExperimentActionReference:
    """An experiment whose stored metrics, filters or configuration reference an action."""

    id: int
    name: str
    created_at: datetime
    created_by: ExperimentCreator | None


@frozen
class ExperimentListWidgetRow:
    """One experiment in the dashboard experiments list widget."""

    id: int
    name: str
    # Public status string: draft, running, paused, exposure_frozen, or stopped.
    status: str
    conclusion: str | None
    start_date: datetime | None
    end_date: datetime | None
    created_at: datetime
    feature_flag_key: str
    created_by: ExperimentCreator | None


@frozen
class ExperimentListWidgetPage:
    rows: tuple[ExperimentListWidgetRow, ...]
    # True when more experiments match than the page holds.
    has_more: bool


@dataclass(frozen=True)
class Experiment:
    """Experiment output."""

    id: int
    name: str
    feature_flag_id: int
    feature_flag_key: str
    is_draft: bool
    created_at: datetime
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    updated_at: datetime | None = None


@frozen
class ExperimentRef:
    """The fields that an object access check reads from one experiment."""

    id: int
    team_id: int
    created_by_id: int | None


@frozen
class ExperimentHandle:
    """The fields of one experiment that the detail actions of the experiment API read before they call the
    facade: what their access checks need, and the ids that their reads take."""

    id: int
    team_id: int
    created_by_id: int | None
    feature_flag_id: int
    feature_flag_created_by_id: int | None
    holdout_id: int | None
    flag_cleanup_task_id: "UUID | None"
    # The connection that a warehouse-native experiment reads, or None for an experiment that reads events.
    warehouse_native_connection_id: str | None


class ExperimentNotFound(Exception):
    """Raised when the project has no live experiment with the id, so a caller at an HTTP boundary can return a 404."""


@frozen
class ExperimentTagChange:
    """The tags of one experiment after a bulk tag change, sorted by name."""

    id: int
    tags: tuple[str, ...]


@frozen
class ExperimentVelocityStats:
    """How many experiments of the team launched, run and ended, which the experiments page shows. The 30-day windows
    end today in the team's timezone. Archived and deleted experiments do not count."""

    launched_last_30d: int
    launched_previous_30d: int
    # The change from `launched_previous_30d` to `launched_last_30d` in percent, rounded to one decimal.
    percent_change: float
    active_experiments: int
    completed_last_30d: int


@frozen
class FlagCleanupTarget:
    """The repository that a flag-cleanup pull request for an experiment would be opened in, and how it was chosen."""

    repository: str | None
    source: Literal["explicit", "team_default", "single_repo", "ambiguous", "no_integration"]
    candidates: tuple[str, ...]


@frozen
class ExposureCohortCreated:
    """The exposure cohort created for an experiment, as the cohort API shows it."""

    cohort: dict[str, Any]


@frozen
class ExperimentTimeseriesResults:
    """The day-by-day results of one metric of an experiment under its current settings. The days are YYYY-MM-DD in
    the project's timezone, and the times are ISO 8601 strings."""

    experiment_id: int
    metric_uuid: str
    status: str
    timeseries: dict[str, Any]
    configuration_by_day: dict[str, str]
    errors: dict[str, str] | None
    computed_at: str | None
    created_at: str
    updated_at: str
    recalculation_status: str | None
    recalculation_created_at: str | None
    formatted_results: str


@frozen
class TimeseriesRecalculationRequest:
    """A backfill of the daily results of one metric. `is_existing` is True when the active backfill of the metric
    already has the current calculation key, so no new backfill was created."""

    id: "UUID"
    experiment_id: int
    metric_uuid: str | None
    fingerprint: str
    status: str
    created_at: str
    is_existing: bool


@frozen
class ExperimentFlag:
    """The feature flag of an experiment, with the fields of the minimal flag shape of the feature flags API."""

    id: int
    team_id: int
    name: str
    # The stored key. A soft-deleted flag keeps its tombstone suffix here.
    key: str
    filters: dict[str, Any]
    deleted: bool
    active: bool
    ensure_experience_continuity: bool | None
    version: int | None
    evaluation_runtime: str | None
    bucketing_identifier: str | None
    evaluation_contexts: tuple[str, ...]


@frozen
class ExperimentHoldoutView:
    """The holdout of an experiment, as the experiment API shows it."""

    id: int
    name: str
    description: str | None
    filters: list[dict[str, Any]]
    created_by: ExperimentCreator | None
    created_at: datetime
    updated_at: datetime


@frozen
class ExperimentSavedMetricLinkView:
    """A shared metric that an experiment uses, as the experiment API shows it.

    `query` names each action by its current name, and carries the calculation key of the link as its
    `fingerprint`. `effective_query` is that query with the overrides from `metadata` applied. It is None when
    the query is not an `ExperimentMetric` of a known metric type, because only those take overrides.
    """

    id: int
    experiment_id: int
    saved_metric_id: int
    name: str
    metadata: dict[str, Any]
    query: dict[str, Any] | None
    effective_query: dict[str, Any] | None
    created_at: datetime


@frozen
class ExperimentBasic:
    """An experiment, as the experiments list shows it.

    `parameters` holds the stored parameters with the flag config keys replaced by the current config of the
    feature flag, or of the rule for an experiment on a flag rule.
    """

    id: int
    team_id: int
    name: str
    description: str | None
    start_date: datetime | None
    end_date: datetime | None
    # The key of the flag without the tombstone suffix of a soft-deleted flag.
    feature_flag_key: str
    feature_flag: ExperimentFlag
    holdout: ExperimentHoldoutView | None
    exposure_cohort_id: int | None
    parameters: dict[str, Any]
    running_time_calculation: dict[str, Any] | None
    excluded_variants: tuple[str, ...] | None
    archived: bool
    deleted: bool | None
    created_by_id: int | None
    created_by: ExperimentCreator | None
    created_at: datetime
    updated_at: datetime
    type: str | None
    conclusion: str | None
    conclusion_comment: str | None
    # Public status string: draft, running, paused, exposure_frozen, or stopped.
    status: str
    # True when an inline or shared metric is an ExperimentTrendsQuery or an ExperimentFunnelsQuery.
    is_legacy: bool
    tags: tuple[str, ...]


@frozen
class ExperimentDetail(ExperimentBasic):
    """An experiment, as the experiment API shows one experiment. The inline metrics name each action by its
    current name."""

    feature_flag_rule_id: "UUID | None"
    holdout_id: int | None
    filters: dict[str, Any]
    secondary_metrics: list[dict[str, Any]] | None
    metrics: list[dict[str, Any]] | None
    metrics_secondary: list[dict[str, Any]] | None
    saved_metrics: tuple[ExperimentSavedMetricLinkView, ...]
    exposure_criteria: dict[str, Any] | None
    stats_config: dict[str, Any] | None
    scheduling_config: dict[str, Any] | None
    primary_metrics_ordered_uuids: list[str] | None
    secondary_metrics_ordered_uuids: list[str] | None
    only_count_matured_users: bool
    version: int | None
    flag_cleanup_task_id: "UUID | None"
    repository: str | None
    can_freeze_exposure: bool
    # The event that exposures are counted on when the experiment configures no custom exposure event.
    resolved_exposure_event: str


@frozen
class ExperimentUpdateTarget:
    """The fields of one experiment that an update of the experiment API reads before it writes: what its access
    check needs, and the state that it checks the input against.

    `parameters` holds what `ExperimentDetail.parameters` holds, so an update that sends back the flag config keys
    that it read compares equal and does not write the flag.
    """

    id: int
    team_id: int
    created_by_id: int | None
    is_draft: bool
    feature_flag_active: bool
    parameters: dict[str, Any]


@frozen
class ExperimentUpdate:
    """The fields that one update of an experiment sets, as the experiment API validated them.

    Only the fields named in `fields_set` are written. The others keep their stored values. The fields are
    declared in the order of the fields of the experiment API, which is the order in which the update hands
    them on.
    """

    fields_set: frozenset[str]
    name: str = ""
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    feature_flag_key: str = ""
    feature_flag_rule_id: "UUID | None" = None
    holdout_id: int | None = None
    # Without the flag config keys, which the update sends as `feature_flag_config`.
    parameters: JsonValue = None
    running_time_calculation: JsonValue = None
    excluded_variants: list[str] | None = None
    secondary_metrics: JsonValue = None
    saved_metrics_ids: list[JsonValue] | None = None
    filters: JsonValue = None
    archived: bool = False
    deleted: bool | None = None
    type: str | None = None
    exposure_criteria: dict[str, JsonValue] | None = None
    metrics: list[JsonValue] | None = None
    metrics_secondary: list[JsonValue] | None = None
    stats_config: JsonValue = None
    scheduling_config: JsonValue = None
    allow_unknown_events: bool = False
    create_in_folder: str = ""
    conclusion: str | None = None
    conclusion_comment: str | None = None
    repository: str | None = None
    primary_metrics_ordered_uuids: list[str] | None = None
    secondary_metrics_ordered_uuids: list[str] | None = None
    only_count_matured_users: bool = False
    update_feature_flag_params: bool = False
    version: int | None = None
    original_experiment: dict[str, JsonValue] | None = None
    # Replace the experiment's tags. None keeps them.
    tags: list[str] | None = None
    # In the flag's own write shape (`{filters, ensure_experience_continuity}`). None leaves the flag config as it is.
    feature_flag_config: dict[str, JsonValue] | None = None
    # True when `feature_flag_config` came from the deprecated flag config keys of `parameters` and changes the flag.
    deprecated_flag_config_changed: bool = False


@frozen
class ExperimentListFilters:
    """The query parameters of the experiments list.

    Each value is the raw text of the query parameter with the same name, so the list parses and refuses it
    the way the API does.
    """

    status: str | None = None
    created_by_id: str | None = None
    archived: str | None = None
    feature_flag_id: str | None = None
    feature_flag_ids: str | None = None
    prompt_name: str | None = None
    event: str | None = None
    tags: str | None = None
    excluded_tags: str | None = None
    search: str | None = None
    order: str | None = None


class WebExperimentNotFound(Exception):
    """Raised when the project has no web experiment with the id."""


@frozen
class WebExperimentConfig:
    """A web experiment, as the web experiments API and the toolbar show it.

    `variants` holds every variant of the feature flag with the rollout percentage that the flag stores, plus
    the transforms that the experiment stores for that variant. When the flag has no variants, it holds the
    variants that the experiment stores.
    """

    id: int
    name: str
    created_at: datetime
    # The stored key of the flag. A soft-deleted flag keeps its tombstone suffix here.
    feature_flag_key: str
    variants: dict[str, Any]


WebExperimentWriteField = Literal["name", "created_at", "variants"]


@frozen
class WebExperimentWrite:
    """The fields of a web experiment that a create or an update sets.

    `fields_set` names the fields that the caller sent. An update sets only those fields. A create needs a
    name and variants, and does not read `created_at`.
    """

    fields_set: frozenset[WebExperimentWriteField]
    name: str | None = None
    created_at: datetime | None = None
    variants: dict[str, Any] | None = None


@frozen
class MetricCalculationKeys:
    """The calculation key of each metric on an experiment. Result rows and the stored metric
    `fingerprint` fields hold these keys."""

    # By metric uuid. When inline metrics share a uuid, the first one in primary-then-secondary order
    # wins, which is the metric the daily calculation computes for that uuid.
    inline: dict[str, str]
    # By saved-metric link id.
    saved: dict[int, str]


@frozen
class DailyMetricCalculation:
    """One metric that the daily timeseries calculation computes for an experiment."""

    experiment_id: int
    team_id: int
    metric_uuid: str
    # The key that files the metric's daily result.
    calculation_key: str


@frozen
class BaselineStats:
    """Sufficient statistics for the control group, mirroring the frontend ``baseline`` object."""

    number_of_samples: int
    sum: float
    sum_squares: float = 0.0
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    numerator_denominator_sum_product: float | None = None
    step_counts: tuple[float, ...] = ()


class RunningTimeMode(LabeledStrEnum):
    # pinned: the page's `ConversionRateInputType` values in frontend/src/types.ts, stored in
    # `running_time_calculation.exposure_estimate_config.conversionRateInputType`.
    AUTOMATIC = "automatic", "Sized from the results"
    MANUAL = "manual", "Saved from a baseline the user entered"


@frozen
class ExperimentDetectableEffectCheckpoint:
    weeks_since_launch: int
    # The smallest relative effect, as a percentage, that the exposures by then detect.
    detectable_effect: float


@frozen
class ExperimentRunningTimeOutlook:
    """What the experiment can detect over time, at its exposure rate so far."""

    days_since_launch: float
    # The exposures that count toward the target, per day from launch to the end of the window the results cover.
    exposures_per_day: float
    # The smallest relative effect, as a percentage, that the exposures so far detect.
    detectable_effect_now: float
    # The next week marks after today.
    upcoming_checkpoints: tuple[ExperimentDetectableEffectCheckpoint, ...]
    # The smallest effect the experiment detects within four weeks from today. A target for a smaller one is out of
    # reach.
    reachable_effect: float


@frozen
class ExperimentRunningTimeTarget:
    """The target sample of an experiment's running time estimate."""

    # The relative effect, as a percentage, that the target sizes the experiment to detect.
    minimum_detectable_effect: float
    # The exposures across the analyzed variants that the experiment needs. None when no stored result can size it.
    recommended_sample_size: int | None
    # The exposures so far that count toward the target: the control's and those of the variants that get traffic.
    # None in manual mode, and when no stored result can size the target.
    current_sample_size: int | None
    # None in manual mode, before the experiment has run long enough to project, and when no stored result can size the
    # target.
    outlook: ExperimentRunningTimeOutlook | None


@frozen
class EndedExperiment:
    id: int
    name: str
    ended_at: datetime


@frozen
class RunningExperiment:
    id: int
    name: str
    started_at: datetime
    flag_key: str


@frozen
class RecentExperiment:
    """One of a team's most recently modified experiments."""

    id: int
    name: str
    archived: bool
    start_date: datetime | None
    end_date: datetime | None
    feature_flag_key: str
    updated_at: datetime


@frozen
class ExperimentOrientation:
    """A team's experiment counts and its most recently modified experiments. Deleted experiments are left out."""

    total_count: int
    # Started, not ended, and not archived.
    running_count: int
    # Most recently modified first.
    recent: tuple[RecentExperiment, ...]


@frozen
class ExperimentChanged:
    """One save or delete of an experiment, as `connect_experiment_changed` receivers get it."""

    team_id: int
    experiment_id: int
    # True only on the save that inserted the row.
    created: bool
    # True on every save that leaves the experiment soft-deleted, and on every hard delete of the row.
    deleted: bool
    # The values the write left on the experiment, so a receiver that mirrors the experiment elsewhere, such as the
    # Vercel sync, does not read the row back.
    name: str
    description: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


@frozen
class DigestLaunchedExperiment:
    team_id: int
    id: int
    name: str
    start_date: datetime


@frozen
class DigestCompletedExperiment:
    team_id: int
    id: int
    name: str
    start_date: datetime | None
    end_date: datetime


@frozen
class TeamExperimentsSettings:
    """A team's experiment settings, as the project settings show them."""

    # Times of day (UTC) as 'HH:00:00' strings. None means the default time.
    experiment_recalculation_times: tuple[str, ...] | None
    default_experiment_confidence_level: Decimal | None
    default_experiment_stats_method: str | None
    experiment_precomputation_enabled: bool
    default_only_count_matured_users: bool
    default_cuped_enabled: bool
    default_cuped_lookback_days: int | None
    default_minimum_detectable_effect: int | None
    default_sequential_testing_enabled: bool
    default_sequential_tuning_parameter: int | None
    flag_cleanup_repository: str | None


class Unset:
    """Marks a setting that an update leaves as it is, because None is a valid value."""


UNSET = Unset()


@frozen
class TeamExperimentsSettingsUpdate:
    """The settings that an update changes. UNSET leaves a setting as it is. Precomputation is not here, because
    PostHog manages it."""

    experiment_recalculation_times: tuple[str, ...] | None | Unset = UNSET
    default_experiment_confidence_level: Decimal | None | Unset = UNSET
    default_experiment_stats_method: str | None | Unset = UNSET
    default_only_count_matured_users: bool | Unset = UNSET
    default_cuped_enabled: bool | Unset = UNSET
    default_cuped_lookback_days: int | None | Unset = UNSET
    default_minimum_detectable_effect: int | None | Unset = UNSET
    default_sequential_testing_enabled: bool | Unset = UNSET
    default_sequential_tuning_parameter: int | None | Unset = UNSET
    flag_cleanup_repository: str | None | Unset = UNSET


@frozen
class LinkedExperiment:
    """An experiment that is not deleted, as the flag or the shared metric it uses lists it."""

    id: int
    name: str
    is_running: bool


@frozen
class ListAccess:
    """Which records the access control rules let a list show the viewer.

    This is the narrowing that `UserAccessControl.filter_queryset_by_access_level` applies to a queryset list.
    With `only_allowed`, the viewer has no resource-level access: the list keeps the allowed ids and the
    viewer's own records. Otherwise it drops the blocked ids, except the viewer's own records.
    """

    viewer_id: int
    only_allowed: bool
    allowed_ids: frozenset[str]
    blocked_ids: frozenset[str]


class SavedMetricNotFound(Exception):
    """Raised when the team has no shared metric with the id."""


@frozen
class SavedMetric:
    """A shared metric, as the shared metrics API shows it.

    `query` names each action it references by the current name of that action. A deleted action keeps the
    name that the metric stored.
    """

    id: int
    team_id: int
    name: str
    description: str | None
    query: dict[str, Any]
    created_by_id: int | None
    created_by: ExperimentCreator | None
    created_at: datetime
    updated_at: datetime
    tags: tuple[str, ...]


@frozen
class SavedMetricListFilters:
    # Each term must match the name, the description or a tag of the metric.
    search_terms: tuple[str, ...] = ()
    # Keeps the metrics whose query references this event, directly or through an action.
    event: str | None = None
    # Keeps the metrics that any of these users created.
    created_by_ids: tuple[int, ...] = ()
    # Keeps the metrics that carry at least one of these tags.
    tags: tuple[str, ...] = ()
    # Keeps the metrics of this type. `funnel` also keeps legacy funnels, and `trend` keeps legacy trends.
    metric_type: SharedMetricType | None = None


SavedMetricWriteField = Literal["name", "description", "query", "tags"]


@frozen
class SavedMetricWrite:
    """The fields of a shared metric that a create or an update sets.

    `fields_set` names the fields that the caller sent. An update keeps the stored value of every other
    field, and keeps the tags unless `tags` is in `fields_set`.
    """

    fields_set: frozenset[SavedMetricWriteField]
    name: str | None = None
    description: str | None = None
    query: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()


@frozen
class StaffTeamExperimentCounts:
    total: int
    running: int


@frozen
class StaffExperiment:
    """An experiment as PostHog Admin shows it to staff."""

    id: int
    name: str
    team_id: int
    team_name: str
    status: str
    is_launched: bool
    is_legacy: bool
    has_malformed_properties: bool
    migrated_from_id: int | None
    migrated_to_id: int | None
    created_at: datetime


@frozen
class StaffSharedMetric:
    id: int
    name: str
    is_legacy: bool
    migrated_to_id: int | None


@frozen
class StaffSavedMetric:
    id: int
    name: str
    team_id: int
    team_name: str
    is_legacy: bool
    migrated_from_id: int | None
    migrated_to_id: int | None


@frozen
class StaffRecalculationFailure:
    metric_uuid: str
    metric_name: str
    error: str


@frozen
class StaffRecalculation:
    """A metrics recalculation run as PostHog Admin shows it to staff."""

    id: str
    experiment_id: int
    team_id: int
    status: str
    trigger: str
    total_metrics: int
    # None in lists, because counting needs a query per run.
    completed_metrics: int | None
    failed_metrics: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration: str | None
    is_terminal: bool
    temporal_url: str
    failures: tuple[StaffRecalculationFailure, ...]


@frozen
class StaffMigration:
    """The new-engine copy of a legacy experiment or shared metric."""

    copy_id: int
    # An earlier migration made the copy, so this one created nothing.
    already_migrated: bool


@frozen
class RecalculationStart:
    outcome: RecalculationStartOutcome
    recalculation_id: str | None = None
    detail: str = ""


@frozen
class Proportion:
    trials: int
    successes: int


@frozen
class ProportionTestResult:
    # Treatment minus control in proportion units, absolute because a control at 0% has no relative change.
    difference: float
    confidence_interval: tuple[float, float]
    p_value: float
    is_significant: bool


@frozen
class MetricRecalculationResult:
    metric_uuid: str
    status: str
    result: dict[str, Any] | None
    error_message: str | None
    configuration_status: str


@frozen
class ActiveRecalculationRun:
    id: str
    status: str


@frozen
class RecalculationRunSummary:
    id: str
    experiment_id: int
    status: str
    total_metrics: int
    completed_metrics: int
    failed_metrics: int
    metric_errors: dict[str, dict[str, Any]]
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    query_to: datetime | None


@frozen
class RequestedRecalculation(RecalculationRunSummary):
    is_existing: bool


@frozen
class RecalculationRun(RecalculationRunSummary):
    metric_retries: dict[str, dict[str, Any]]
    results: tuple[MetricRecalculationResult, ...]
    rows_read: int | None = None
    estimated_rows_total: int | None = None


@frozen
class LatestRecalculation(RecalculationRun):
    active_run: ActiveRecalculationRun | None
    result_source: Literal["recalculation", "timeseries_fallback"]
    exceeds_recalculation_age_limit: bool


class WarehouseNativeResultAccessDenied(Exception):
    """Raised when the reader may not read the stored results of a warehouse-native experiment. The detail is written
    for the reader, so a caller at an HTTP boundary can return it as a 403."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
