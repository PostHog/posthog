from django.db import models
from django.utils import timezone
import uuid


class Issue(models.Model):
    class Status(models.TextChoices):
        BACKLOG = "backlog", "Backlog"
        TODO = "todo", "To Do"
        IN_PROGRESS = "in_progress", "In Progress"
        TESTING = "testing", "Testing"
        DONE = "done", "Done"

    class OriginProduct(models.TextChoices):
        ERROR_TRACKING = "error_tracking", "Error Tracking"
        EVAL_CLUSTERS = "eval_clusters", "Eval Clusters"
        USER_CREATED = "user_created", "User Created"
        SUPPORT_QUEUE = "support_queue", "Support Queue"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.BACKLOG)
    origin_product = models.CharField(max_length=20, choices=OriginProduct.choices)
    position = models.IntegerField(default=0)

    # GitHub integration fields (issue-specific)
    github_branch = models.CharField(max_length=255, blank=True, null=True, help_text="Branch created for this issue")
    github_pr_url = models.URLField(blank=True, null=True, help_text="Pull request URL when created")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_issue"
        managed = True
        ordering = ["position"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def github_integration(self):
        """Get the team's main GitHub integration if available"""
        from posthog.models.integration import Integration
        try:
            return Integration.objects.filter(
                team_id=self.team_id,
                kind="github"
            ).first()
        except Exception:
            return None


class IssueProgress(models.Model):
    """Tracks real-time progress of Claude Code execution for issues."""

    class Status(models.TextChoices):
        STARTED = "started", "Started"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="progress_logs")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # Progress tracking
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED)
    current_step = models.CharField(max_length=255, blank=True, help_text="Current step being executed")
    total_steps = models.IntegerField(default=0, help_text="Total number of steps if known")
    completed_steps = models.IntegerField(default=0, help_text="Number of completed steps")

    # Claude Code output
    output_log = models.TextField(blank=True, help_text="Live output from Claude Code execution")
    error_message = models.TextField(blank=True, help_text="Error message if execution failed")

    # Workflow metadata
    workflow_id = models.CharField(max_length=255, blank=True, help_text="Temporal workflow ID")
    workflow_run_id = models.CharField(max_length=255, blank=True, help_text="Temporal workflow run ID")
    activity_id = models.CharField(max_length=255, blank=True, help_text="Temporal activity ID")

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_issue_progress"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Progress for {self.issue.title} - {self.get_status_display()}"

    def append_output(self, text: str):
        """Append text to the output log and save."""
        if self.output_log:
            self.output_log += "\n" + text
        else:
            self.output_log = text
        self.updated_at = timezone.now()
        self.save(update_fields=["output_log", "updated_at"])

    def update_progress(self, step: str = None, completed_steps: int = None, total_steps: int = None):
        """Update progress information."""
        if step:
            self.current_step = step
        if completed_steps is not None:
            self.completed_steps = completed_steps
        if total_steps is not None:
            self.total_steps = total_steps
        self.updated_at = timezone.now()
        self.save(update_fields=["current_step", "completed_steps", "total_steps", "updated_at"])

    def mark_completed(self):
        """Mark the progress as completed."""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    def mark_failed(self, error: str):
        """Mark the progress as failed with an error message."""
        self.status = self.Status.FAILED
        self.error_message = error
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at"])

    @property
    def progress_percentage(self):
        """Calculate progress percentage."""
        if self.total_steps and self.total_steps > 0:
            return min(100, (self.completed_steps / self.total_steps) * 100)
        return 0
