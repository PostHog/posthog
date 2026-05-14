"""Django models for mcp_analytics."""

from django.db import models

from posthog.models.utils import UUIDModel


# TODO(mcp-sessions): this MCPSession model is a SCAFFOLD. The real
# posthog_mcp_session table is being built in parallel and will replace
# this one. When that lands, delete this class and its migration, and
# update products/mcp_analytics/backend/intent_clustering.py:fetch_intent_corpus
# to read from the real table instead.
class MCPSession(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    session_id = models.CharField(max_length=200, db_index=True)
    conversation_id = models.CharField(max_length=200, blank=True, default="", db_index=True)
    intent = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_mcp_session"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "session_id"]),
            models.Index(fields=["team", "conversation_id"]),
        ]


class MCPIntentClusterSnapshot(models.Model):
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
