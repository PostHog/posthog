from typing import TYPE_CHECKING

from django.db import models

import tiktoken

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.kafka_client.client import ProduceResult

EMBEDDING_MODEL_TOKEN_LIMIT = 8192

MAX_WATCHED_QUESTIONS_PER_TEAM = 50


class AgentMemory(UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="agent_memories",
    )
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_memories",
    )
    contents = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "id"]),
        ]

    def embed(self, model_name: str) -> "ProduceResult":
        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(self.contents))
        if token_count > EMBEDDING_MODEL_TOKEN_LIMIT:
            raise ValueError(
                f"Memory content exceeds {EMBEDDING_MODEL_TOKEN_LIMIT} token limit for embedding model (got {token_count} tokens)"
            )

        from posthog.api.embedding_worker import emit_embedding_request

        embedding_metadata = {**self.metadata}
        if self.user_id is not None:
            embedding_metadata["user_id"] = str(self.user_id)

        return emit_embedding_request(
            content=self.contents,
            team_id=self.team_id,
            product="posthog-ai",
            document_type="memory",
            rendering="plaintext",
            document_id=str(self.id),
            models=[model_name],
            timestamp=self.created_at,
            metadata=embedding_metadata,
        )


class TrackedQuestion(ModelActivityMixin, UUIDModel):
    """A Max AI answer that the user has chosen to watch on a cadence.

    Each cadence forks the originating conversation, lets Max compare against the baseline, and
    emits a Signal if the drift judge marks the change as material.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    class Cadence(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="tracked_questions",
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracked_questions",
    )

    source_conversation = models.ForeignKey(
        "ee.Conversation",
        on_delete=models.CASCADE,
        related_name="tracked_questions",
    )
    source_human_message_id = models.UUIDField()
    source_visualization_message_id = models.UUIDField()

    title = models.CharField(max_length=255)
    question_text = models.TextField()
    baseline_summary = models.TextField(blank=True, default="")
    baseline_captured_at = models.DateTimeField()

    cadence = models.CharField(
        max_length=10,
        choices=Cadence,
        default=Cadence.WEEKLY,
    )
    status = models.CharField(
        max_length=10,
        choices=Status,
        default=Status.ACTIVE,
    )
    next_run_at = models.DateTimeField(db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    repository = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    activity_logging_on_delete = True

    class Meta:
        indexes = [
            models.Index(fields=["team", "status", "next_run_at"], name="ph_ai_tq_due_idx"),
            models.Index(fields=["team", "source_conversation"], name="ph_ai_tq_team_conv_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_conversation", "source_visualization_message_id"],
                name="unique_tracked_question_per_message",
            )
        ]


class TrackedQuestionRun(UUIDModel):
    """One execution of a TrackedQuestion's drift check.

    Records the forked conversation Max ran in, its narrative, the judge verdict, and whether a
    Signal was emitted downstream.
    """

    class State(models.TextChoices):
        OK = "ok", "OK"
        DRIFTED = "drifted", "Drifted"
        ERROR = "error", "Error"
        SKIPPED = "skipped", "Skipped"

    class Severity(models.TextChoices):
        NONE = "none", "None"
        MINOR = "minor", "Minor"
        MODERATE = "moderate", "Moderate"
        SIGNIFICANT = "significant", "Significant"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    tracked_question = models.ForeignKey(
        TrackedQuestion,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    forked_conversation = models.ForeignKey(
        "ee.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parent_question_runs",
    )

    state = models.CharField(max_length=10, choices=State, default=State.OK)
    severity = models.CharField(max_length=12, choices=Severity, default=Severity.NONE)

    narrative = models.TextField(blank=True, default="")
    judge_summary = models.TextField(blank=True, default="")
    judge_payload = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")

    signal_emitted_at = models.DateTimeField(null=True, blank=True)
    signal_source_id = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["tracked_question", "-created_at"], name="ph_ai_tq_run_chrono_idx"),
        ]
