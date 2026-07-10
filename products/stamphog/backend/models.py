"""
Django models for stamphog.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

import uuid

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin

from .facade.enums import ReviewRunStatus, ReviewVerdict


# Inherits TeamScopedRootMixin so models opt into fail-closed team scoping —
# queries without team context raise TeamScopeError instead of silently
# returning every team's rows. See posthog/models/scoping/README.md.
class StamphogRepoConfig(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    # Full name in "owner/repo" form, matching the GitHub webhook payload.
    repository = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    github_installation_id = models.CharField(max_length=64)
    policy_overrides = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "repository"], name="unique_stamphog_repo_per_team"),
        ]

    def __str__(self) -> str:
        return self.repository


class ReviewRun(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    repo_config = models.ForeignKey(StamphogRepoConfig, on_delete=models.CASCADE, related_name="review_runs")
    pr_number = models.IntegerField()
    pr_url = models.CharField(max_length=512)
    head_sha = models.CharField(max_length=64)
    # GitHub webhook delivery id — unique so a redelivered event dedupes.
    delivery_id = models.CharField(max_length=64, null=True, unique=True)
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in ReviewRunStatus],
        default=ReviewRunStatus.QUEUED,
    )
    verdict = models.CharField(
        max_length=32,
        choices=[(v.value, v.value) for v in ReviewVerdict],
        default=ReviewVerdict.NONE,
    )
    gate_result = models.JSONField(null=True)
    output = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True)

    def __str__(self) -> str:
        return f"{self.repo_config.repository}#{self.pr_number} ({self.status})"
