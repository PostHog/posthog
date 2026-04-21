import logging

from django.contrib.postgres.fields import ArrayField
from django.db import models

from django_deprecate_fields import deprecate_field

from posthog.models.team.extensions import register_team_extension_signal
from posthog.models.utils import UUIDModel

logger = logging.getLogger(__name__)


class SignalSourceConfig(UUIDModel):
    class SourceProduct(models.TextChoices):
        SESSION_REPLAY = "session_replay", "Session replay"
        LLM_ANALYTICS = "llm_analytics", "LLM analytics"
        GITHUB = "github", "GitHub"
        LINEAR = "linear", "Linear"
        ZENDESK = "zendesk", "Zendesk"
        CONVERSATIONS = "conversations", "Conversations"
        ERROR_TRACKING = "error_tracking", "Error tracking"

    class SourceType(models.TextChoices):
        SESSION_ANALYSIS_CLUSTER = "session_analysis_cluster", "Session analysis cluster"
        EVALUATION = "evaluation", "Evaluation"
        ISSUE = "issue", "Issue"
        TICKET = "ticket", "Ticket"
        ISSUE_CREATED = "issue_created", "Issue created"
        ISSUE_REOPENED = "issue_reopened", "Issue reopened"
        ISSUE_SPIKING = "issue_spiking", "Issue spiking"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="signal_source_configs")
    source_product = models.CharField(max_length=100, choices=SourceProduct.choices)
    source_type = models.CharField(max_length=100, choices=SourceType.choices)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    @classmethod
    def is_source_enabled(cls, team_id: int, source_product: str, source_type: str) -> bool:
        """Check whether a given signal source is enabled for a team.

        LLM analytics signals are always allowed (gated in llma evals workflows). TODO - this should be moved here.
        For everything else, the team must have a SignalSourceConfig row with enabled=True.
        """
        if source_product == cls.SourceProduct.LLM_ANALYTICS:
            return True

        # Session problem signals are emitted as part of session analysis,
        # so they're gated by the pre-existing session_analysis_cluster config
        if source_product == cls.SourceProduct.SESSION_REPLAY and source_type == "session_problem":
            source_type = cls.SourceType.SESSION_ANALYSIS_CLUSTER

        return cls.objects.filter(
            team_id=team_id,
            source_product=source_product,
            source_type=source_type,
            enabled=True,
        ).exists()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_product", "source_type"], name="unique_team_source_product_type"
            )
        ]


class AutonomyPriority(models.TextChoices):
    P0 = "P0", "P0"
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"
    P4 = "P4", "P4"


class SignalTeamConfig(UUIDModel):
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_team_config",
    )
    default_autostart_priority = models.CharField(
        max_length=2, choices=AutonomyPriority.choices, default=AutonomyPriority.P0
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal team config"
        verbose_name_plural = "Signal team configs"


register_team_extension_signal(SignalTeamConfig, logger=logger)


class SignalUserAutonomyConfig(UUIDModel):
    user = models.OneToOneField("posthog.User", on_delete=models.CASCADE, related_name="signal_autonomy_config")
    autostart_priority = models.CharField(max_length=2, choices=AutonomyPriority.choices, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal user autonomy config"
        verbose_name_plural = "Signal user autonomy configs"


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
    # How many times the summary workflow has run for this report (incremented on each CANDIDATE -> IN_PROGRESS).
    run_count = models.IntegerField(default=0)

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
            # - POTENTIAL -> CANDIDATE when the report is selected for summary generation
            # - READY -> CANDIDATE to update the report with new signals context (every N signals)
            case (S.POTENTIAL | S.READY, S.CANDIDATE):
                self.promoted_at = timezone.now()
                updated_fields.add("promoted_at")

            case (S.CANDIDATE, S.IN_PROGRESS):
                if signals_at_run_increment is None:
                    raise ValueError("signals_at_run_increment is required for candidate -> in_progress")
                self.last_run_at = timezone.now()
                self.signals_at_run = self.signal_count + signals_at_run_increment
                self.run_count += 1
                updated_fields.update(["last_run_at", "signals_at_run", "run_count"])

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

            # Reset to potential (from in_progress via actionability judge, from suppressed, or by user snooze on a ready report)
            case (S.IN_PROGRESS | S.SUPPRESSED | S.READY, S.POTENTIAL):
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


class SignalEmissionRecord(UUIDModel):
    """Tracks which source records have been emitted as signals.

    Owned by the signals app so source models (e.g. Ticket) stay decoupled.
    One row per source record, upserted on emission.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source_product = models.CharField(max_length=100)
    source_type = models.CharField(max_length=100)
    source_id = models.CharField(max_length=200)
    emitted_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_product", "source_type", "source_id"],
                name="unique_signal_emission_record",
            )
        ]
        indexes = [
            models.Index(
                fields=["team", "source_product", "source_type"],
                name="signals_emission_lookup_idx",
            )
        ]


class SignalReportArtefact(UUIDModel):
    class ArtefactType(models.TextChoices):
        VIDEO_SEGMENT = "video_segment"
        SAFETY_JUDGMENT = "safety_judgment"
        ACTIONABILITY_JUDGMENT = "actionability_judgment"
        PRIORITY_JUDGMENT = "priority_judgment"
        SIGNAL_FINDING = "signal_finding"
        REPO_SELECTION = "repo_selection"
        SUGGESTED_REVIEWERS = "suggested_reviewers"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100, choices=ArtefactType.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["report"], name="signals_sig_report__idx"),
            # For JOINs involving matching a report to artifact of a certain type
            models.Index(fields=["report", "type"], name="signals_sig_report_type_idx"),
        ]


class SignalReportTask(UUIDModel):
    class Relationship(models.TextChoices):
        REPO_SELECTION = "repo_selection"
        RESEARCH = "research"
        IMPLEMENTATION = "implementation"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="report_tasks")
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="signal_report_tasks")
    relationship = models.CharField(max_length=200, choices=Relationship.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signal report task"
        verbose_name_plural = "Signal report tasks"
