"""
Facade contracts (DTOs) for experiments product.

These are framework-free frozen dataclasses that define the interface
between the experiments product and the rest of the system.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

if TYPE_CHECKING:
    from posthog.schema import MaxExperimentSummaryContext

# Metrics per section (primary/secondary) included in the AI results summary
MAX_METRICS_TO_SUMMARIZE = 50


@frozen
class ExperimentSummaryData:
    """Result of fetching experiment data for the AI results summary."""

    context: "MaxExperimentSummaryContext"
    last_refresh: datetime | None
    pending_calculation: bool
    omitted_metric_count: int


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
    EXPOSURE_CRITERIA_CANNOT_MATCH = "exposure_criteria_cannot_match"
    SRM = "srm", "Sample Ratio Mismatch"
    ZERO_EXPOSURES = "zero_exposures"
    FORCED_VARIANT_RELEASE_CONDITION = "forced_variant_release_condition"
    FLAG_VARIANTS_MISMATCH = "flag_variants_mismatch"
    SPLIT_CHANGED_MID_RUN = "split_changed_mid_run"
    BUCKETING_CHANGED_MID_RUN = "bucketing_changed_mid_run"
    RELEASE_CONDITIONS_CHANGED_MID_RUN = "release_conditions_changed_mid_run"
    NEW_FLAG_NO_TRAFFIC = "new_flag_no_traffic"
    EARLY_SIGNIFICANCE = "early_significance"


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
    EXPOSURE_CRITERIA_CANNOT_MATCH = "exposure_criteria_cannot_match"
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
