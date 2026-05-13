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
    mermaid_before = models.TextField(blank=True, default="")
    mermaid_after = models.TextField(blank=True, default="")
    steps_before = models.JSONField(default=list)
    steps_after = models.JSONField(default=list)
    summary = models.TextField(blank=True, default="")
    truncated = models.BooleanField(default=False)
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
