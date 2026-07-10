"""
Django models for stamphog.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from __future__ import annotations

import uuid

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel

from .facade.enums import ReviewRunStatus, ReviewVerdict


# Lives on a separate product database (see products/db_routing.yaml), so it
# inherits ProductTeamModel: team_id is a plain BigIntegerField (no cross-DB FK
# to Team) and the manager is fail-closed. See posthog/models/scoping/README.md.
class StamphogRepoConfig(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # SCM provider this config talks to. GitHub is the only implemented provider
    # today, but the installation/repository identity is provider-scoped so the
    # field is part of the cross-team uniqueness identity.
    provider = models.CharField(max_length=32, default="github")
    # Full name in "owner/repo" form, matching the GitHub webhook payload.
    repository = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    installation_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "repository"], name="unique_stamphog_repo_per_team"),
        ]

    def __str__(self) -> str:
        return self.repository


class ReviewRun(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_config = models.ForeignKey(StamphogRepoConfig, on_delete=models.CASCADE, related_name="review_runs")
    pr_number = models.IntegerField()
    pr_url = models.CharField(max_length=512)
    head_sha = models.CharField(max_length=64)
    # Branch name of the PR head (pull_request.head.ref). Named to match the
    # engineering_analytics / GitHub-DWH head_sha/head_branch/pr_number convention.
    head_branch = models.CharField(max_length=255, blank=True)
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
    # What we posted back to the SCM once the verdict was decided — recorded so a
    # re-review can find and update its own artifacts, and for audit. Populated by
    # the post_verdict activity (and the gate-block path) from the API responses.
    verdict_posted_at = models.DateTimeField(null=True)
    posted_review_id = models.BigIntegerField(null=True)
    posted_comment_id = models.BigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True)

    def __str__(self) -> str:
        return f"{self.repo_config.repository}#{self.pr_number} ({self.status})"
