"""Django models for mcp_analytics."""

from django.db import models

from posthog.models.utils import UUIDModel


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
