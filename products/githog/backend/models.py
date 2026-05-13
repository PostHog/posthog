"""Django models for githog."""

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
    """Per-user persisted widget layout for a single PR workspace.

    The layout is a small JSON document describing widget positions and sizes on the
    PR review grid. We key by (team, user, repository, pr_number) so each user keeps
    their own arrangement of widgets per PR.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+")
    repository = models.CharField(max_length=255)
    pr_number = models.IntegerField()
    layout = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "repository", "pr_number"],
                name="unique_githog_pr_layout_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "user", "repository", "pr_number"]),
        ]


class GitHogConversationMessage(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    repository = models.CharField(max_length=512, help_text="Repository in owner/name format.")
    pull_request_number = models.IntegerField()
    author = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
