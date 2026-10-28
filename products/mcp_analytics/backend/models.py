"""Django models for mcp_analytics."""

from typing import TYPE_CHECKING, ClassVar

from django.db import models

from posthog.models.scoping.manager import TeamScopedManager, TeamScopedQuerySet
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    import numpy as np


class MCPIntentClusterSnapshot(TeamScopedRootMixin):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        COMPUTING = "computing", "Computing"
        ERROR = "error", "Error"

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="mcp_intent_cluster_snapshot",
    )
    last_computed_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDLE)
    error_message = models.TextField(blank=True, default="")
    # Full denormalized snapshot: {clusters: [{id, label, intent_count, ...}], computed_with: {...}}
    clusters = models.JSONField(default=dict)
    last_computed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_mcp_analytics_intent_cluster_snapshot"


class MCPAnalyticsSubmission(UUIDModel):
    class Kind(models.TextChoices):
        FEEDBACK = "feedback", "Feedback"
        MISSING_CAPABILITY = "missing_capability", "Missing capability"

    class FeedbackCategory(models.TextChoices):
        RESULTS = "results", "Results"
        USABILITY = "usability", "Usability"
        BUG = "bug", "Bug"
        DOCS = "docs", "Docs"
        OTHER = "other", "Other"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    kind = models.CharField(max_length=32, choices=Kind)
    goal = models.TextField()
    summary = models.TextField()
    category = models.CharField(max_length=32, choices=FeedbackCategory, blank=True, default="")
    blocked = models.BooleanField(null=True, blank=True)
    attempted_tool = models.CharField(max_length=200, blank=True, default="")

    mcp_client_name = models.CharField(max_length=200, blank=True, default="")
    mcp_client_version = models.CharField(max_length=100, blank=True, default="")
    mcp_protocol_version = models.CharField(max_length=50, blank=True, default="")
    mcp_transport = models.CharField(max_length=50, blank=True, default="")
    mcp_session_id = models.CharField(max_length=200, blank=True, default="")
    mcp_trace_id = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_mcp_analytics_submission"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "kind", "-created_at"]),
            models.Index(fields=["team", "attempted_tool"]),
            models.Index(fields=["team", "mcp_session_id"]),
            models.Index(fields=["team", "mcp_trace_id"]),
        ]


class MCPIntentEmbeddingCache(UUIDModel, TeamScopedRootMixin):
    """Content-addressable embedding cache for intent clustering.

    Keyed on ``(team, content_hash, model)``: same text re-embedded with the
    same model returns the cached bytes. Embeddings are stored as raw
    little-endian float32 bytes — vector arithmetic happens in numpy, never
    in Postgres, so a typed Postgres array buys us nothing.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    content_hash = models.CharField(max_length=64)
    model = models.CharField(max_length=64)
    embedding = models.BinaryField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_mcp_analytics_intent_embedding_cache"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "content_hash", "model"],
                name="unique_mcp_intent_embedding_cache",
            ),
        ]
        indexes = [
            # Drives the (per-team) TTL sweep activity. Composite (team, created_at)
            # so Postgres can skip directly to a team's rows instead of a global
            # index scan-then-filter.
            models.Index(fields=["team", "created_at"]),
        ]


class MCPSession(UUIDModel, TeamScopedRootMixin):
    # On-demand intent store keyed by (team, session_id). The session list itself
    # is aggregated on the fly from $mcp_tool_call events (see logic.py); the
    # backfill that once populated session_start/_end/duration/etc. is gone.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    session_id = models.CharField(max_length=128)
    intent = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_mcp_session"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["team", "session_id"], name="unique_mcp_session"),
        ]


class ActiveTopicManager(TeamScopedManager["MCPIntentTopic"]):
    # The base for_team() and unscoped() build a fresh queryset without get_queryset(), so each one repeats the filter.
    def get_queryset(self) -> TeamScopedQuerySet["MCPIntentTopic"]:
        return super().get_queryset().filter(status=MCPIntentTopic.Status.ACTIVE)

    def for_team(self, team_id: int, *, canonical: bool = False) -> TeamScopedQuerySet["MCPIntentTopic"]:
        return super().for_team(team_id, canonical=canonical).filter(status=MCPIntentTopic.Status.ACTIVE)

    def unscoped(self) -> TeamScopedQuerySet["MCPIntentTopic"]:
        return super().unscoped().filter(status=MCPIntentTopic.Status.ACTIVE)


class MCPIntentTopic(UUIDModel, TeamScopedRootMixin):
    """One stable intent topic per team.

    A weekly re-fit matches fresh clusters to these rows by centroid similarity, so a topic keeps
    its id across runs and trend questions can span months. ``centroid`` is raw little-endian
    float32 bytes, the same encoding as ``MCPIntentEmbeddingCache``.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    # No database constraint: creating one locks posthog_team, a hot table.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    label = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default="")
    centroid = models.BinaryField()
    centroid_x = models.FloatField(default=0.0)
    centroid_y = models.FloatField(default=0.0)
    # Members further than this cosine distance from the centroid are outliers.
    outlier_distance = models.FloatField(default=1.0)
    member_count = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    last_run_id = models.CharField(max_length=100, blank=True, default="")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    objects: ClassVar[TeamScopedManager["MCPIntentTopic"]] = TeamScopedManager()  # type: ignore[assignment]
    active: ClassVar[ActiveTopicManager] = ActiveTopicManager()

    class Meta:
        db_table = "posthog_mcp_analytics_intent_topic"
        indexes = [models.Index(fields=["team", "status"])]

    @staticmethod
    def encode_centroid(vector: "np.ndarray") -> bytes:
        import numpy as np

        return np.asarray(vector, dtype=np.float32).tobytes()

    def decoded_centroid(self) -> "np.ndarray":
        import numpy as np

        return np.frombuffer(bytes(self.centroid), dtype=np.float32)


class MCPIntentClusteringRun(UUIDModel, TeamScopedRootMixin):
    """Bookkeeping for one pipeline run (hourly sync, nightly assign, weekly refit)."""

    class Kind(models.TextChoices):
        SYNC = "sync", "Sync embeddings"
        ASSIGN = "assign", "Assign topics"
        REFIT = "refit", "Refit topics"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        SKIPPED_NO_CONSENT = "skipped_no_consent", "Skipped: no AI data processing consent"
        SKIPPED_TOO_FEW = "skipped_too_few", "Skipped: too few intents"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    run_id = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RUNNING)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    n_intents = models.IntegerField(default=0)
    n_topics = models.IntegerField(default=0)
    n_outliers = models.IntegerField(default=0)
    n_embeddings_requested = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    params = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_mcp_analytics_intent_clustering_run"
        indexes = [models.Index(fields=["team", "kind", "-started_at"])]
        constraints = [models.UniqueConstraint(fields=["team", "run_id"], name="unique_mcp_intent_clustering_run")]
