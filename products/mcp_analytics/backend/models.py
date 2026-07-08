"""Django models for mcp_analytics."""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


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

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
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

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
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
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    session_id = models.CharField(max_length=64)
    intent = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_mcp_session"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["team", "session_id"], name="unique_mcp_session"),
        ]
