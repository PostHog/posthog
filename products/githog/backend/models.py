"""Django models for githog."""

from django.conf import settings
from django.db import models


class GitHogPullRequestDataFlow(models.Model):
    """Cached LLM-generated execution-flow analysis for a single PR head SHA.

    Keyed by (team, repository, pr_number, head_sha) so the cache invalidates
    whenever new commits change the head SHA.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    repository = models.CharField(max_length=255)
    pr_number = models.IntegerField()
    head_sha = models.CharField(max_length=64)
    base_sha = models.CharField(max_length=64)
    flow_before = models.JSONField(default=dict)
    flow_after = models.JSONField(default=dict)
    steps_before = models.JSONField(default=list)
    steps_after = models.JSONField(default=list)
    summary = models.TextField(blank=True, default="")
    truncated = models.BooleanField(default=False)
    files_total = models.IntegerField(default=0)
    files_with_content = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "repository", "pr_number", "head_sha"],
                name="unique_githog_pr_dataflow_per_head_sha",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "repository", "pr_number"]),
        ]


class GitHogPullRequestLayout(models.Model):
    """Per-user persisted widget layout for the PR workspace.

    The layout is a small JSON document describing widget positions and sizes on the
    PR review grid. It is scoped to the user only — once a user sets a layout, every
    PR (across any repo or team) renders with that same arrangement.
    """

    user = models.OneToOneField(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="githog_pr_layout",
    )
    layout = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class GitHogPullRequestMessage(models.Model):
    """A single message in the per-PR conversation thread.

    The thread is implicit: messages with the same (team, repository, pr_number)
    form one conversation, ordered by ``created_at``. Authors are kept as a FK so
    we can render avatars and names from the existing user model.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    repository = models.CharField(max_length=255)
    pr_number = models.IntegerField()
    body = models.TextField()
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "repository", "pr_number", "created_at"]),
        ]
        ordering = ["created_at", "id"]
