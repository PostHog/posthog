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
    BIAS_RISK_MULTIPLE_EXCLUDED = "bias_risk_multiple_excluded"


class ExperimentHealthFindingSeverity(LabeledStrEnum):
    # The values are the severities of the platform's health issues (posthog/models/health_issue.py), so a
    # finding can become a health issue by value. The labels differ on purpose: two choice sets with the same
    # values and labels share one OpenAPI enum, and the generated name of the other one would change.
    CRITICAL = "critical", "Critical severity"
    WARNING = "warning", "Warning severity"
    INFO = "info", "Info severity"


class ExperimentHealthFindingActionKind(LabeledStrEnum):
    ADJUST_DISTRIBUTION = "adjust_distribution"
    USE_FIRST_SEEN_VARIANT = "use_first_seen_variant"


@frozen
class ExperimentHealthFinding:
    """One problem that a health check found in an experiment, with what fixes it."""

    code: ExperimentHealthFindingCode
    subcode: str | None
    severity: ExperimentHealthFindingSeverity
    title: str
    detail: str
    evidence: Mapping[str, str | int | float | None]
    actions: tuple[ExperimentHealthFindingActionKind, ...]
    diagnostic_ref: str | None


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
