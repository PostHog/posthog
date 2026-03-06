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


class InvalidStatusTransition(Exception):
    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Cannot transition from {from_status} to {to_status}")


class SignalReport(UUIDModel):
    class Status(models.TextChoices):
        POTENTIAL = "potential"
        CANDIDATE = "candidate"
        IN_PROGRESS = "in_progress"
        PENDING_INPUT = "pending_input"
        READY = "ready"
        FAILED = "failed"
        DELETED = "deleted"
        SUPPRESSED = "suppressed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POTENTIAL)

    total_weight = models.FloatField(default=0.0)
    signal_count = models.IntegerField(default=0)

    # Forward-looking promotion threshold: a potential report only promotes when signal_count >= this.
    # Incremented each summary run to prevent re-promoting on every signal.
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

    def transition_to(
        self,
        new_status: "SignalReport.Status",
        *,
        snooze_for: int | None = None,
        signals_at_run_increment: int | None = None,
        reset_weight: bool = False,
        title: str | None = None,
        summary: str | None = None,
        error: str | None = None,
    ) -> list[str]:
        """
        Validate and apply a status transition with side effects.
        Returns the list of fields that were modified.

        Raises InvalidStatusTransition if the transition is not allowed.
        Does NOT call .save().
        """
        from django.utils import timezone

        S = self.Status
        updated_fields: set[str] = set()

        match (self.status, new_status):
            # Pipeline transitions
            case (S.POTENTIAL, S.CANDIDATE):
                self.promoted_at = timezone.now()
                updated_fields.add("promoted_at")

            case (S.CANDIDATE, S.IN_PROGRESS):
                if signals_at_run_increment is None:
                    raise ValueError("signals_at_run_increment is required for candidate -> in_progress")
                self.last_run_at = timezone.now()
                self.signals_at_run = self.signal_count + signals_at_run_increment
                updated_fields.update(["last_run_at", "signals_at_run"])

            case (S.IN_PROGRESS, S.READY):
                if title is None or summary is None:
                    raise ValueError("title and summary are required for in_progress -> ready")
                self.title = title
                self.summary = summary
                self.error = None
                updated_fields.update(["title", "summary", "error"])

            case (S.IN_PROGRESS, S.PENDING_INPUT):
                if title is None or summary is None or error is None:
                    raise ValueError("title, summary, and error are required for in_progress -> pending_input")
                self.title = title
                self.summary = summary
                self.error = error
                updated_fields.update(["title", "summary", "error"])

            # Reset to potential (from in_progress via actionability judge, or from suppressed)
            case (S.IN_PROGRESS | S.SUPPRESSED, S.POTENTIAL):
                self.promoted_at = None
                updated_fields.add("promoted_at")
                if snooze_for is not None:
                    self.signals_at_run = self.signal_count + snooze_for
                    updated_fields.add("signals_at_run")
                if reset_weight:
                    self.total_weight = 0.0
                    updated_fields.add("total_weight")
                if error is not None:
                    self.error = error
                    updated_fields.add("error")

            # Any non-deleted status can fail
            case (S.POTENTIAL | S.CANDIDATE | S.IN_PROGRESS | S.PENDING_INPUT | S.READY, S.FAILED):
                if error is None:
                    raise ValueError("error is required for transition to failed")
                self.error = error
                updated_fields.add("error")

            # Any non-deleted status can be suppressed
            case (S.POTENTIAL | S.CANDIDATE | S.IN_PROGRESS | S.PENDING_INPUT | S.READY | S.FAILED, S.SUPPRESSED):
                self.promoted_at = None
                updated_fields.add("promoted_at")

            # Any non-deleted status can be deleted
            case (
                S.POTENTIAL | S.CANDIDATE | S.IN_PROGRESS | S.PENDING_INPUT | S.READY | S.FAILED | S.SUPPRESSED,
                S.DELETED,
            ):
                pass

            case _:
                raise InvalidStatusTransition(self.status, new_status)

        self.status = new_status
        updated_fields.update(["status", "updated_at"])
        return list(updated_fields)


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
