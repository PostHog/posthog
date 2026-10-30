"""
Facade contracts (DTOs) for experiments product.

These are framework-free frozen dataclasses that define the interface
between the experiments product and the rest of the system.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

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
    METRIC_CANNOT_COMPILE = "metric_cannot_compile"
    METRIC_CALCULATION_FAILED = "metric_calculation_failed"
    EXPOSURE_CRITERIA_CANNOT_MATCH = "exposure_criteria_cannot_match"
    EXPOSURE_FILTER_ON_DYNAMIC_COHORT = "exposure_filter_on_dynamic_cohort"
    EXPOSURE_FILTER_EXCLUDES_EVENTS = "exposure_filter_excludes_events"
    SRM = "srm", "Sample Ratio Mismatch"
    ZERO_EXPOSURES = "zero_exposures"
    FORCED_VARIANT_RELEASE_CONDITION = "forced_variant_release_condition"
    FLAG_VARIANTS_MISMATCH = "flag_variants_mismatch"
    SPLIT_CHANGED_MID_RUN = "split_changed_mid_run"
    BUCKETING_CHANGED_MID_RUN = "bucketing_changed_mid_run"
    RELEASE_CONDITIONS_CHANGED_MID_RUN = "release_conditions_changed_mid_run"
    NEW_FLAG_NO_TRAFFIC = "new_flag_no_traffic"
    EARLY_SIGNIFICANCE = "early_significance"


class ExperimentHealthMetricCompileErrorKind(LabeledStrEnum):
    # A validation error of the query builder, written for the user.
    REJECTED = "rejected"
    # HogQL can't parse an expression of the metric.
    SYNTAX = "syntax"
    # HogQL can't compile the query.
    QUERY = "query"
    # The stored definition doesn't parse into a metric.
    DEFINITION = "definition"


class HealthExposureInputsStatus(LabeledStrEnum):
    READY = "ready"
    # The cached answer is past its age. A recalculation runs in the background, or the last one failed.
    STALE = "stale"
    # No cached answer. A calculation runs in the background.
    CALCULATING = "calculating"
    NOT_LAUNCHED = "not_launched"
    NO_QUERY_ACCESS = "no_query_access"
    # The query could not be built, or no answer is cached and the last background calculation failed.
    FAILED = "failed"


class ExperimentHealthInputsTrafficStatus(LabeledStrEnum):
    READ = "read"
    NOT_NEEDED = "not_needed"
    NO_QUERY_ACCESS = "no_query_access"
    # The reader is denied a flag call property that the scan reads.
    DENIED_PROPERTIES = "denied_properties"
    NO_FLAG_VERSION = "no_flag_version"
    # The scan failed or was too expensive, which is cached so that it does not run again on every load. Or another
    # request's scan was still running and did not answer in time.
    UNKNOWN = "unknown"


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


class ExperimentHealthCheckKey(LabeledStrEnum):
    # pinned: the health endpoint and the exposure query return these values, so API callers depend on them. A key
    # names the check, not a problem: `flag_state` reports four finding codes, and `flag_history` reports its finding
    # under `split_changed_mid_run`.
    FLAG_STATE = "flag_state"
    FLAG_HISTORY = "flag_history"
    SPLIT_CHANGED_MID_RUN = "split_changed_mid_run"
    BUCKETING_CHANGED_MID_RUN = "bucketing_changed_mid_run"
    RELEASE_CONDITIONS_CHANGED_MID_RUN = "release_conditions_changed_mid_run"
    FLAG_VARIANTS_MISMATCH = "flag_variants_mismatch"
    FORCED_VARIANT_RELEASE_CONDITION = "forced_variant_release_condition"
    NEW_FLAG_NO_TRAFFIC = "new_flag_no_traffic"
    NO_METRIC = "no_metric"
    METRIC_EVENT_NOT_INGESTED = "metric_event_not_ingested"
    METRIC_CANNOT_COMPILE = "metric_cannot_compile"
    METRIC_CALCULATION_FAILED = "metric_calculation_failed"
    EXPOSURE_CRITERIA_CANNOT_MATCH = "exposure_criteria_cannot_match"
    EXPOSURE_FILTERS = "exposure_filters"
    EARLY_SIGNIFICANCE = "early_significance"
    ZERO_EXPOSURES = "zero_exposures"
    SRM = "srm"
    BIAS_RISK_MULTIPLE_EXCLUDED = "bias_risk_multiple_excluded"
    MULTIPLE_VARIANTS_SHARE = "multiple_variants_share"


class ExperimentHealthCheckStatus(LabeledStrEnum):
    PASSED = "passed"
    FINDING = "finding"
    NOT_APPLICABLE = "not_applicable"
    # The check covers the experiment, but it could not read an input or it failed, so a problem can go unreported.
    NOT_CHECKED = "not_checked"


@frozen
class ExperimentHealthCheckResult:
    key: ExperimentHealthCheckKey
    name: str
    status: ExperimentHealthCheckStatus
    # Why the check did not look, for the statuses not_applicable and not_checked. None otherwise.
    reason: str | None


@frozen
class ExperimentHealth:
    findings: tuple[ExperimentHealthFinding, ...]
    checks: tuple[ExperimentHealthCheckResult, ...]


@frozen
class ExperimentHealthReaderAccess:
    """What the caller of the health checks may read, for the checks that read more than the experiment."""

    can_read_flag_history: bool
    can_query_events: bool
    denied_event_properties: frozenset[str]


class ExperimentValidationError(Exception):
    """Raised when the facade refuses an experiment write for its input. The message is written for the person who
    sent the input, so a caller at an HTTP boundary can return it as a 400."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        # The input field that the message is about, so that an HTTP boundary can report the error on that field.
        # None when the message is about the input as a whole.
        self.field = field


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
    """An experiment that is not deleted, as the flag it uses lists it."""

    id: int
    name: str
    is_running: bool
