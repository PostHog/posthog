from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .facade.enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)


class WarehouseSuggestion(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    kind = models.CharField(max_length=32, choices=WarehouseSuggestionKind.choices)
    fingerprint = models.CharField(max_length=64)
    subject_kind = models.CharField(max_length=16, choices=WarehouseSuggestionSubjectKind.choices)
    subject_id = models.UUIDField()
    payload = models.JSONField(default=dict)
    payload_version = models.PositiveSmallIntegerField(default=1)
    rules_version = models.CharField(max_length=32)
    evidence = models.JSONField(default=dict)
    evidence_window_start = models.DateTimeField()
    evidence_window_end = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    reproposed_count = models.PositiveIntegerField(default=0)
    score = models.FloatField()
    score_inputs = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=WarehouseSuggestionStatus.choices, default=WarehouseSuggestionStatus.PROPOSED.value
    )
    surfaced_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    dismissal_reason = models.CharField(
        max_length=16, choices=WarehouseSuggestionDismissalReason.choices, null=True, blank=True
    )
    dismissal_note = models.TextField(null=True, blank=True)
    dismissed_at_score = models.FloatField(null=True, blank=True)
    created_asset = models.JSONField(null=True, blank=True)
    asset_outcome = models.CharField(
        max_length=16, choices=WarehouseSuggestionAssetOutcome.choices, null=True, blank=True
    )
    run_id = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "fingerprint"], name="warehouse_suggestion_unique_fingerprint"),
        ]
        indexes = [
            models.Index(fields=["team", "status", "kind"], name="warehouse_sugg_status_kind"),
            models.Index(fields=["team", "last_seen_at"], name="warehouse_sugg_last_seen"),
        ]


class WarehouseSuggestionTeamConfig(models.Model):
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    enabled = models.BooleanField(default=True)
    paused_reason = models.CharField(max_length=32, null=True, blank=True)
    eligible = models.BooleanField(default=False)
    days_with_data = models.PositiveSmallIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
