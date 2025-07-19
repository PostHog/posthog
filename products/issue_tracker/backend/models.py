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

    # GitHub integration fields
    github_repo_url = models.URLField(
        blank=True, null=True, help_text="GitHub repository URL (e.g., https://github.com/owner/repo)"
    )
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
