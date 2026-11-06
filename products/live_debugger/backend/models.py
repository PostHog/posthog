from django.db import models

from posthog.models.utils import UUIDModel


class LiveDebuggerBreakpoint(UUIDModel):
    """The live debugger product is retired. The model stays so that Django keeps cascading team
    deletes into its table. A later migration removes the model and drops the table."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    repository = models.TextField(null=True, blank=True)  # Format: "owner/repo" (e.g., "PostHog/posthog")
    filename = models.TextField()
    line_number = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)
    condition = models.TextField(blank=True, null=True)  # Optional condition for conditional breakpoints
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_livedebuggerbreakpoint"
        managed = True
        constraints = [
            models.UniqueConstraint(
                fields=["team", "repository", "filename", "line_number"],
                name="unique_breakpoint_per_line_per_file_per_repo_per_team",
            )
        ]
        indexes = [
            models.Index(fields=["team_id", "repository"], name="live_debug_team_repo_idx"),
        ]
