"""Django models for metrics."""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel

# Define your models here
# Important:
# - Keep models thin, no business logic, use logic.py instead
# - Use types from facade/contracts.py or facade/enums.py where applicable
# - Do not use ForeignKeys to models outside this app unless allowed, as you will make implicit dependencies.
# - If you make a ForeignKey to a common model, disallow reverse relations with related_name='+'


class MetricsDashboardTemplate(UUIDTModel):
    """A dashboard in the bank of metrics dashboards.

    The bank is instance-wide. A curated template comes from the code. A generated template comes from the
    metric names of one team, and teams see it only after a staff member approves it.
    """

    class Source(models.TextChoices):
        CURATED = "curated", "Curated"
        GENERATED = "generated", "Generated"

    class Status(models.TextChoices):
        GENERATING = "generating", "Generating"
        PENDING_REVIEW = "pending_review", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    key = models.CharField(
        max_length=200,
        unique=True,
        help_text="Stable identity: the file name of a curated template, or a digest of the metric names for a generated one.",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    source = models.CharField(max_length=16, choices=Source.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    metric_names = ArrayField(
        models.CharField(max_length=400),
        default=list,
        blank=True,
        help_text="The metric names that the panels read. Matching compares them with the metric names of a team.",
    )
    panels = models.JSONField(default=list, blank=True, help_text="The panels, each with an insight query and a box.")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    generation = models.JSONField(
        default=dict, blank=True, help_text="The record of the AI generation: rounds, pictures and verdicts."
    )
    # The team whose metrics a generated template came from. Its pictures live there.
    source_team_id = models.BigIntegerField(null=True, blank=True)
    # The unlisted dashboard that shows the template with live data, for the AI checks and the staff review.
    preview_team_id = models.BigIntegerField(null=True, blank=True)
    preview_dashboard_id = models.BigIntegerField(null=True, blank=True)
    # db_constraint=False keeps the migration off the locks on posthog_user.
    reviewed_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "-created_at"], name="metrics_dash_tpl_status_idx")]

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class MetricsDashboardSuggestion(TeamScopedRootMixin, UUIDTModel):
    """A template that suits the metrics of a team. The suggested dashboards menu lists these."""

    # db_constraint=False keeps the migration off the locks on posthog_team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    template = models.ForeignKey(MetricsDashboardTemplate, on_delete=models.CASCADE, related_name="suggestions")
    matched_metric_names = ArrayField(models.CharField(max_length=400), default=list, blank=True)
    coverage = models.FloatField(default=0, help_text="The share of the template panels whose metrics the team sends.")
    reason = models.CharField(max_length=300, blank=True, default="")
    dashboard_id = models.BigIntegerField(
        null=True, blank=True, help_text="The dashboard that a user of the team created from the suggestion."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "template"], name="metrics_dash_suggestion_unique_template")
        ]


class MetricsDashboardDiscovery(TeamScopedRootMixin, UUIDTModel):
    """What the dashboard discovery last saw of the metric names of a team."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    names_fingerprint = models.BigIntegerField(
        default=0, help_text="A digest of the recent metric names, so that a sweep skips a team with no change."
    )
    analyzed_metric_names = ArrayField(
        models.CharField(max_length=400),
        default=list,
        blank=True,
        help_text="The metric names that the last analysis read. A name outside this list is new.",
    )
    bank_revision = models.CharField(max_length=64, blank=True, default="")
    analyzed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team"], name="metrics_dash_discovery_unique_team")]
