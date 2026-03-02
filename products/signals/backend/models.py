from django.contrib.postgres.fields import ArrayField
from django.db import models

from django_deprecate_fields import deprecate_field

from posthog.models.utils import UUIDModel


class SignalSourceConfig(UUIDModel):
    class SourceProduct(models.TextChoices):
        SESSION_REPLAY = "session_replay", "Session replay"
        LLM_ANALYTICS = "llm_analytics", "LLM analytics"

    class SourceType(models.TextChoices):
        SESSION_ANALYSIS_CLUSTER = "session_analysis_cluster", "Session analysis cluster"
        EVALUATION = "evaluation", "Evaluation"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="signal_source_configs")
    source_product = models.CharField(max_length=100, choices=SourceProduct.choices)
    source_type = models.CharField(max_length=100, choices=SourceType.choices)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_product", "source_type"], name="unique_team_source_product_type"
            )
        ]


class SignalReport(UUIDModel):
    class Status(models.TextChoices):
        POTENTIAL = "potential"
        CANDIDATE = "candidate"
        IN_PROGRESS = "in_progress"
        PENDING_INPUT = "pending_input"
        READY = "ready"
        FAILED = "failed"
        # User-initiated lifecycle stages
        DELETED = "deleted"  # Soft-deleted; hidden from inbox but preserved in DB
        SUPPRESSED = "suppressed"  # Gathering signals indefinitely; never exits this state
        # Note: snoozing is implemented via status=POTENTIAL + signals_at_run threshold (no dedicated state)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POTENTIAL)

    total_weight = models.FloatField(default=0.0)
    signal_count = models.IntegerField(default=0)

    # Forward-looking promotion threshold: a potential report only promotes when signal_count >= this.
    # Incremented by SIGNALS_AT_RUN_INCREMENT each summary run to prevent re-promoting on every signal.
    # The snooze action sets it to signal_count + N to delay re-promotion by N signals.
    signals_at_run = models.IntegerField(default=0)

    # LLM-generated during signal matching
    title = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    # Video segment clustering fields
    cluster_centroid = deprecate_field(
        ArrayField(
            base_field=models.FloatField(),
            blank=True,
            null=True,
            help_text="Embedding centroid for this report's video segment cluster",
        )
    )
    cluster_centroid_updated_at = deprecate_field(models.DateTimeField(blank=True, null=True))
    # Deprecated - unused
    conversation = deprecate_field(
        models.ForeignKey("ee.Conversation", null=True, blank=True, on_delete=models.SET_NULL)
    )
    relevant_user_count = deprecate_field(models.IntegerField(blank=True, null=True))

    class Meta:
        indexes = [
            models.Index(fields=["team", "status", "promoted_at"]),
            models.Index(fields=["team", "created_at"]),
        ]


class SignalReportArtefact(UUIDModel):
    class ArtefactType(models.TextChoices):
        VIDEO_SEGMENT = "video_segment"
        SAFETY_JUDGMENT = "safety_judgment"
        ACTIONABILITY_JUDGMENT = "actionability_judgment"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100, choices=ArtefactType.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["report"], name="signals_sig_report__idx"),
        ]
