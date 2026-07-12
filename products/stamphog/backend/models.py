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

from .facade.enums import ChannelResolutionSource, DigestRunStatus, ReviewRunStatus, ReviewVerdict


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
    # Opt-in: capture merged PRs and fold them into the daily Slack digest. Independent of
    # `enabled` (review) so a repo can be reviewed without digests, or vice versa.
    digest_enabled = models.BooleanField(default=False)
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


class DigestChannel(ProductTeamModel):
    """One Slack destination for a digest audience.

    The `audience_key` is a plain opaque string produced by the single audience cascade at
    capture time (see logic/audiences.py): PR author -> GitHub team slug -> "repo:{repository}"
    fallback. A row can be created by a human (API) or auto-provisioned when the workspace has a
    channel named exactly like the audience_key (see logic/channel_resolution.py) —
    `resolution_source` records which.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audience_key = models.CharField(max_length=255)
    # Plain id of a main-DB posthog.Integration row (kind="slack"). No FK: this model lives on a
    # separate product DB and can't hold a cross-database constraint — the id is resolved against
    # the main DB (with a team_id + kind guard) when the digest is posted.
    slack_integration_id = models.BigIntegerField()
    slack_channel_id = models.CharField(max_length=64)
    slack_channel_name = models.CharField(max_length=255, blank=True)
    # How this row came to exist — manual (API/human), an automatic Slack-name match, or (future)
    # an owners.yaml contact.slack resolution. Auto-provisioned rows never override a human's.
    resolution_source = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in ChannelResolutionSource],
        default=ChannelResolutionSource.MANUAL,
    )
    enabled = models.BooleanField(default=True)
    last_digest_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "audience_key"], name="unique_stamphog_digest_audience_per_team"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.audience_key} -> {self.slack_channel_name or self.slack_channel_id}"


class DigestRun(ProductTeamModel):
    """One posted (or attempted) daily digest for a channel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    digest_channel = models.ForeignKey(DigestChannel, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in DigestRunStatus],
        default=DigestRunStatus.PENDING,
    )
    pr_count = models.IntegerField(default=0)
    # LLM (or fallback) summary output that was rendered into the Slack message.
    summary = models.JSONField(default=dict)
    slack_message_ts = models.CharField(max_length=32, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True)

    def __str__(self) -> str:
        return f"digest {self.digest_channel_id} ({self.status})"


class MergedPullRequest(ProductTeamModel):
    """A merged PR captured from the webhook, awaiting inclusion in a digest.

    A row is linked to a `DigestRun` once it has been summarized and posted. Unlinked rows
    (digest_run is NULL) are what the next digest picks up, so a failed post leaves them for
    tomorrow to retry.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_config = models.ForeignKey(StamphogRepoConfig, on_delete=models.CASCADE, related_name="merged_pull_requests")
    pr_number = models.IntegerField()
    pr_url = models.CharField(max_length=512)
    title = models.CharField(max_length=512)
    author_login = models.CharField(max_length=255)
    merged_at = models.DateTimeField()
    merge_commit_sha = models.CharField(max_length=64)
    head_branch = models.CharField(max_length=255, blank=True)
    additions = models.IntegerField(default=0)
    deletions = models.IntegerField(default=0)
    changed_files = models.IntegerField(default=0)
    # Trimmed PR description, capped at capture time to keep rows (and the LLM prompt) bounded.
    body_excerpt = models.TextField(blank=True)
    # Digest bucket resolved at capture time by the audience cascade (see logic/audiences.py).
    audience_key = models.CharField(max_length=255, blank=True)
    # GitHub webhook delivery id — unique so a redelivered merge event dedupes.
    delivery_id = models.CharField(max_length=64, null=True, unique=True)
    digest_run = models.ForeignKey(DigestRun, on_delete=models.SET_NULL, null=True, related_name="merged_pull_requests")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "repo_config", "pr_number"], name="unique_stamphog_merged_pr"),
        ]

    def __str__(self) -> str:
        return f"{self.repo_config.repository}#{self.pr_number} (merged)"
