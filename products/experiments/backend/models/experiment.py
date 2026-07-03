from typing import TYPE_CHECKING, Any

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.file_system.constants import DEFAULT_SURFACE
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import RootTeamMixin, UUIDModel

if TYPE_CHECKING:
    from posthog.models.team import Team


# Structured key stamped on each feature-flag release group when an experiment's exposure is frozen.
# Frozen-exposure state is derived from this key, not stored on the experiment — the same spirit as
# is_paused being derived from feature_flag.active rather than persisted. Unknown group keys pass
# through flag validation and are ignored by the Rust flag matcher, so this is additive metadata;
# that pass-through contract is pinned by test_flag_update_after_freeze_preserves_frozen_state.
EXPOSURE_FROZEN_GROUP_KEY = "exposure_frozen"

# Companion key recording which snapshot cohort the freeze AND-ed into the group, so unfreezing
# can remove exactly that condition even if users added their own cohort conditions meanwhile.
EXPOSURE_FROZEN_COHORT_KEY = "exposure_frozen_cohort"

# Human-readable note prepended to each release group's `description` when freezing. Purely
# informational — the description stays user-editable prose and carries no state.
EXPOSURE_FROZEN_GROUP_MARKER = "Added automatically when the experiment exposure was frozen to stop new enrollment."


class Experiment(FileSystemSyncMixin, ModelActivityMixin, RootTeamMixin, models.Model):
    class ExperimentType(models.TextChoices):
        WEB = "web", "web"
        PRODUCT = "product", "product"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RUNNING = "running", "Running"
        STOPPED = "stopped", "Stopped"

    name = models.CharField(max_length=400)
    description = models.CharField(max_length=3000, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # Filters define the target metric of an Experiment
    filters = models.JSONField(default=dict, blank=True)

    # DEPRECATED: catch-all config blob being split into dedicated homes.
    # Feature flag config (feature_flag_variants, rollout_percentage, aggregation_group_type_index,
    # feature_flag_payloads, ensure_experience_continuity) belongs on the linked FeatureFlag.
    # Running-time calculator state (minimum_detectable_effect, recommended_running_time,
    # recommended_sample_size, exposure_estimate_config) belongs in `running_time_calculation`.
    # Do not add new keys here.
    parameters = models.JSONField(default=dict, null=True)

    # A list of filters for secondary metrics
    secondary_metrics = models.JSONField(default=list, null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)
    feature_flag = models.ForeignKey("feature_flags.FeatureFlag", blank=False, on_delete=models.RESTRICT)
    exposure_cohort = models.ForeignKey("cohorts.Cohort", on_delete=models.SET_NULL, null=True, blank=True)
    holdout = models.ForeignKey("ExperimentHoldout", on_delete=models.SET_NULL, null=True, blank=True)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)
    # Whether archiving this experiment also auto-archived its linked feature flag,
    # so unarchiving only undoes an archive the experiment itself performed.
    feature_flag_auto_archived = models.BooleanField(default=False, db_default=False)
    deleted = models.BooleanField(default=False, null=True)
    type = models.CharField(max_length=40, choices=ExperimentType, null=True, blank=True, default="product")
    variants = models.JSONField(default=dict, null=True, blank=True)

    exposure_criteria = models.JSONField(default=dict, null=True, blank=True)

    metrics = models.JSONField(default=list, null=True, blank=True)
    metrics_secondary = models.JSONField(default=list, null=True, blank=True)
    primary_metrics_ordered_uuids = models.JSONField(default=None, null=True, blank=True)
    secondary_metrics_ordered_uuids = models.JSONField(default=None, null=True, blank=True)
    saved_metrics: models.ManyToManyField = models.ManyToManyField(
        "ExperimentSavedMetric", blank=True, related_name="experiments", through="ExperimentToSavedMetric"
    )

    stats_config = models.JSONField(default=dict, null=True, blank=True)
    scheduling_config = models.JSONField(default=dict, null=True, blank=True)

    # Running-time calculator state: minimum_detectable_effect, recommended_running_time,
    # recommended_sample_size, exposure_estimate_config. Canonical home for these keys,
    # which historically lived in `parameters`.
    running_time_calculation = models.JSONField(default=dict, null=True, blank=True)

    # Variant keys dropped from statistical analysis. Canonical home for what historically
    # lived in `parameters.excluded_variants`. `null`/empty both mean "no exclusions".
    excluded_variants = ArrayField(models.TextField(), null=True, blank=True)

    only_count_matured_users = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=Status,
        default=None,
        null=True,
        blank=True,
    )

    conclusion = models.CharField(
        max_length=30,
        choices=[
            ("won", "Won"),
            ("lost", "Lost"),
            ("inconclusive", "Inconclusive"),
            ("stopped_early", "Stopped Early"),
            ("invalid", "Invalid"),
        ],
        null=True,
        blank=True,
    )
    conclusion_comment = models.TextField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "posthog_experiment"

    def __str__(self):
        return self.name or "Untitled"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.status = self.computed_status
        if "update_fields" in kwargs:
            kwargs["update_fields"] = [*list(kwargs["update_fields"]), "status"]
        super().save(*args, **kwargs)

    @property
    def is_launched(self) -> bool:
        return self.start_date is not None

    @property
    def is_draft(self) -> bool:
        return not self.is_launched

    @property
    def is_running(self) -> bool:
        return self.is_launched and self.end_date is None

    @property
    def is_stopped(self) -> bool:
        return self.is_launched and self.end_date is not None

    @property
    def is_paused(self) -> bool:
        # Pause is not stored on the experiment — it is the running state with the linked flag deactivated.
        return self.is_running and self.feature_flag_id is not None and not self.feature_flag.active

    @property
    def is_exposure_frozen(self) -> bool:
        # Frozen exposure is not stored on the experiment — it is the running state with the linked flag's
        # release groups narrowed to a static snapshot of the already-exposed cohort. We detect it from the
        # structured key stamped on each group when the cohort condition was AND'd in — the same predicate
        # the JSONB-containment filter uses in the experiments list endpoint.
        if not self.is_running or self.feature_flag_id is None:
            return False
        groups = (self.feature_flag.filters or {}).get("groups", [])
        return any(group.get(EXPOSURE_FROZEN_GROUP_KEY) is True for group in groups)

    @property
    def computed_status(self) -> "Experiment.Status":
        if self.is_stopped:
            return Experiment.Status.STOPPED
        if self.is_running:
            return Experiment.Status.RUNNING
        return Experiment.Status.DRAFT

    @property
    def status_label(self) -> str:
        """Public status string (draft/running/paused/exposure_frozen/stopped) — single source for the API
        serializer and dashboard widgets."""
        if self.is_exposure_frozen:
            return "exposure_frozen"
        if self.is_paused:
            return "paused"
        return self.status or self.computed_status.value

    def get_feature_flag_key(self):
        # Strip the soft-delete tombstone so the API and analytics surface the original
        # key, matching what the query runners resolve against historical events.
        return self.feature_flag.key_without_tombstone()

    def get_analytics_metadata(self) -> dict[str, Any]:
        variants = self.feature_flag.variants

        return {
            "experiment_id": self.id,
            "experiment_name": self.name,
            "feature_flag_key": self.get_feature_flag_key(),
            "type": self.type,
            "status": self.status or self.computed_status,
            "metrics_count": len(self.metrics or []),
            "secondary_metrics_count": len(self.metrics_secondary or []),
            "saved_metrics_count": self.saved_metrics.count(),
            "has_description": bool(self.description),
            "has_conclusion_comment": bool(self.conclusion_comment),
            "variant_count": len(variants),
            "created_at": self.created_at,
        }

    def get_stats_config(self, key: str):
        return self.stats_config.get(key) if self.stats_config else None

    @classmethod
    def get_file_system_unfiled(cls, team: "Team", surface: str = DEFAULT_SURFACE) -> QuerySet["Experiment"]:
        base_qs = cls.objects.filter(team=team).exclude(deleted=True)
        return cls._filter_unfiled_queryset(base_qs, team, type="experiment", ref_field="id", surface=surface)

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Experiments"),
            type="experiment",  # sync with APIScopeObject in scopes.py
            ref=str(self.id),
            name=self.name or "Untitled",
            href=f"/experiments/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=False,  # always keep in FileSystem
        )


def _live_experiments_for_flag(feature_flag_id: Any) -> "QuerySet[Experiment]":
    """Single source of truth for the `has_experiment` predicate: a flag has a linked
    experiment iff a non-deleted Experiment row references it. The Rust flags service
    (rust/feature-flags/src/flags/feature_flag_list.rs) mirrors this in hand-written SQL —
    keep the two in lockstep.

    Accepts a concrete id or an `OuterRef`, so it backs both helpers below.
    """
    return Experiment.objects.filter(feature_flag_id=feature_flag_id, deleted=False)


def live_experiment_exists() -> Exists:
    """`Exists` subquery for `.annotate()` over many flags. For a single in-hand flag, use `flag_has_live_experiment`."""
    return Exists(_live_experiments_for_flag(OuterRef("pk")))


def flag_has_live_experiment(feature_flag_id: int) -> bool:
    """Instance-level companion to `live_experiment_exists` — same predicate, one flag."""
    return _live_experiments_for_flag(feature_flag_id).exists()


def holdout_filters_for_flag(holdout_id: int | None, filters: list | None) -> dict:
    """Return the `holdout` field for a feature flag's filters."""
    if not holdout_id or not filters:
        return {"holdout": None}
    return {
        "holdout": {"id": holdout_id, "exclusion_percentage": filters[0]["rollout_percentage"]},
    }


LEGACY_METRIC_KINDS: frozenset[str] = frozenset({"ExperimentTrendsQuery", "ExperimentFunnelsQuery"})


def experiment_has_legacy_metrics(experiment: "Experiment") -> bool:
    """Check if experiment uses legacy metric formats."""
    # Check inline metrics
    all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
    if any(m.get("kind") in LEGACY_METRIC_KINDS for m in all_metrics):
        return True

    # Check saved metrics
    if experiment.experimenttosavedmetric_set.filter(saved_metric__query__kind__in=LEGACY_METRIC_KINDS).exists():
        return True

    return False


def saved_metric_has_legacy_query(saved_metric: "ExperimentSavedMetric") -> bool:
    """Check if saved metric uses legacy query format."""
    return saved_metric.query.get("kind") in LEGACY_METRIC_KINDS if saved_metric.query else False


class ExperimentHoldout(ModelActivityMixin, RootTeamMixin, models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # Filters define the definition of the holdout
    # This is then replicated across flags for experiments in the holdout
    filters = models.JSONField(default=list)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_experimentholdout"

    def save(self, *args: Any, skip_activity_log: bool = False, **kwargs: Any) -> None:
        if skip_activity_log:
            # Bypass ModelActivityMixin.save() and call Model.save() directly
            super(ModelActivityMixin, self).save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class ExperimentSavedMetric(ModelActivityMixin, RootTeamMixin, models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    query = models.JSONField()

    # Metadata for the saved metric
    # has things like if this metric was migrated from a legacy metric
    metadata = models.JSONField(null=True, blank=True, default=dict)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_experimentsavedmetric"


class ExperimentToSavedMetric(ModelActivityMixin, models.Model):
    activity_logging_on_delete = True

    experiment = models.ForeignKey("Experiment", on_delete=models.CASCADE)
    saved_metric = models.ForeignKey("ExperimentSavedMetric", on_delete=models.CASCADE)

    # Metadata for the saved metric at the time of the experiment creation
    # has stuff like whether this metric is primary, it has breakdowns,
    # and any other information we need for the metric, other than the query.
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_experimenttosavedmetric"

    def __str__(self):
        return f"{self.experiment.name} - {self.saved_metric.name} - {self.metadata}"


class ExperimentMetricResult(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    experiment = models.ForeignKey("Experiment", on_delete=models.CASCADE)
    metric_uuid = models.CharField(max_length=255)
    fingerprint = models.CharField(max_length=64, null=True, blank=True)  # SHA256 hash is 64 chars
    query_from = models.DateTimeField()
    query_to = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    result = models.JSONField(null=True, blank=True, default=None)
    query_id = models.CharField(max_length=255, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["experiment", "metric_uuid", "query_to"]
        indexes = [
            models.Index(fields=["experiment", "metric_uuid", "query_to"]),
        ]
        db_table = "posthog_experimentmetricresult"

    def __str__(self):
        return f"ExperimentMetricResult({self.experiment_id}, {self.metric_uuid}, {self.query_from}, {self.status})"


class ExperimentTimeseriesRecalculation(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    experiment = models.ForeignKey("Experiment", on_delete=models.CASCADE)
    metric = models.JSONField()
    fingerprint = models.CharField(max_length=64)  # SHA256 hash

    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    last_successful_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "fingerprint"],
                condition=models.Q(status__in=["pending", "in_progress"]),
                name="unique_active_recalculation_per_experiment_metric",
            ),
        ]
        db_table = "posthog_experimenttimeseriesrecalculation"

    def __str__(self):
        metric_uuid = self.metric.get("uuid", "unknown")
        return f"ExperimentTimeseriesRecalculation(exp={self.experiment_id}, metric={metric_uuid}, fingerprint={self.fingerprint}, status={self.status})"


class ExperimentMetricsRecalculation(TeamScopedRootMixin, UUIDModel):
    """Tracks batch recalculation of all metrics for an experiment.

    The primary key (`id`, a uuid7 from UUIDModel) is the recalculation_id passed to the recalculation workflow.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual"
        COLD_RUN = "cold_run", "Cold Run"
        STALE_REFRESH = "stale_refresh", "Stale Refresh"
        AUTO_REFRESH = "auto_refresh", "Auto Refresh"
        CONFIG_CHANGE = "config_change", "Config Change"
        # Deprecated: never emitted, retained for old rows.
        EXPERIMENT_LAUNCH = "experiment_launch", "Experiment Launch"
        EXPERIMENT_STOP = "experiment_stop", "Experiment Stop"
        EXPERIMENT_UPDATE = "experiment_update", "Experiment Update"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    experiment = models.ForeignKey("Experiment", on_delete=models.CASCADE)

    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    total_metrics = models.PositiveIntegerField(default=0)
    metric_errors = models.JSONField(default=dict)
    # Internal: written by the discovery activity, used by the service to recompute recalc fingerprints. Not exposed by the API serializer.
    metric_uuids = models.JSONField(default=list)

    # Single data-window end shared by all metrics in the run. Set once when the run starts; every metric
    # (including retries) uses this value so all metrics cover the same window and retries overwrite rather than
    # orphan rows. Exposed by the API serializer as the data freshness cutoff for the run's results.
    query_to = models.DateTimeField(null=True, blank=True)

    trigger = models.CharField(max_length=30, choices=Trigger, default=Trigger.MANUAL)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["experiment", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment"],
                condition=models.Q(status__in=["pending", "in_progress"]),
                name="unique_active_metrics_recalculation_per_experiment",
            ),
        ]
        db_table = "posthog_experimentmetricsrecalculation"

    def __str__(self):
        return f"ExperimentMetricsRecalculation(exp={self.experiment_id}, status={self.status}, total={self.total_metrics})"
