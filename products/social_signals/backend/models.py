"""Django models for social_signals."""

from __future__ import annotations

import secrets
import uuid

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel

from .facade.enums import (
    AnalysisStatus,
    AnalyzerKind,
    MentionType,
    Platform,
    ProcessingStatus,
    SourceKind,
)


def _generate_ingest_token() -> str:
    """Opaque per-team webhook token. URL-safe, ~43 chars."""
    return secrets.token_urlsafe(32)


class MentionSource(ProductTeamModel):
    """A configured ingestion endpoint for a team.

    One row per ``(team_id, kind)``. Holds the per-team webhook ``ingest_token``
    that the third-party service POSTs to. The token is the credential.
    """

    # nosemgrep: prefer-uuid7-django-pk -- product convention: random UUID4 PKs
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    kind = models.CharField(
        max_length=64,
        choices=[(k.value, k.value) for k in SourceKind],
    )
    enabled = models.BooleanField(default=True)
    ingest_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=_generate_ingest_token,
    )
    # Source-specific knobs (e.g. octolens project id, polling cursor, …).
    config = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "kind"],
                name="ss_unique_source_per_team_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} (team {self.team_id})"

    def rotate_token(self) -> str:
        self.ingest_token = _generate_ingest_token()
        self.save(update_fields=["ingest_token", "updated_at"])
        return self.ingest_token


class Mention(ProductTeamModel):
    """A single inbound social mention.

    Idempotent on ``(team_id, source, external_id)`` — repeat webhook deliveries
    update fields but don't create duplicates and don't re-dispatch analyzers.
    """

    # nosemgrep: prefer-uuid7-django-pk -- product convention: random UUID4 PKs
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source = models.ForeignKey(
        MentionSource,
        on_delete=models.CASCADE,
        related_name="mentions",
    )
    platform = models.CharField(
        max_length=32,
        choices=[(p.value, p.value) for p in Platform],
        default=Platform.OTHER,
    )
    mention_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.value) for t in MentionType],
        default=MentionType.POST,
    )

    # Dedup key (per source): whatever stable identifier the source exposes.
    external_id = models.CharField(max_length=512)

    # Content
    url = models.URLField(max_length=2048, blank=True)
    content = models.TextField(blank=True)
    language = models.CharField(max_length=16, blank=True)

    # Author
    author_handle = models.CharField(max_length=255, blank=True)
    author_display_name = models.CharField(max_length=255, blank=True)
    author_profile_url = models.URLField(max_length=2048, blank=True)
    author_followers = models.IntegerField(null=True, blank=True)

    # Timestamps: posted_at is the author's; captured_at is ours
    posted_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    # Engagement counts; shape varies by platform
    engagement = models.JSONField(default=dict, blank=True)

    # Raw original payload — kept so analyzers / re-processing don't need to
    # refetch from the source. Cap size at the ingestion adapter layer.
    raw_payload = models.JSONField(default=dict, blank=True)

    # Pipeline state
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in ProcessingStatus],
        default=ProcessingStatus.PENDING,
    )
    last_error = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "source", "external_id"],
                name="ss_unique_mention_per_source",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "platform", "-posted_at"], name="ss_mention_team_plat_posted"),
            models.Index(fields=["team_id", "-captured_at"], name="ss_mention_team_captured"),
            models.Index(fields=["team_id", "status"], name="ss_mention_team_status"),
        ]
        ordering = ["-captured_at"]

    def __str__(self) -> str:
        snippet = (self.content or self.external_id)[:48]
        return f"{self.platform}: {snippet}"


class MentionAnalysis(ProductTeamModel):
    """One analyzer's result for one mention.

    Unique on ``(mention, kind)`` — re-running an analyzer overwrites its row
    rather than appending. Different analyzers attach independent rows.
    """

    # nosemgrep: prefer-uuid7-django-pk -- product convention: random UUID4 PKs
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    mention = models.ForeignKey(
        Mention,
        on_delete=models.CASCADE,
        related_name="analyses",
    )
    kind = models.CharField(
        max_length=64,
        choices=[(k.value, k.value) for k in AnalyzerKind],
    )
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in AnalysisStatus],
        default=AnalysisStatus.PENDING,
    )

    # Structured analyzer output — schema varies per analyzer kind. Document
    # the shape in each analyzer module's docstring.
    result = models.JSONField(default=dict, blank=True)
    model_used = models.CharField(max_length=128, blank=True)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mention", "kind"],
                name="ss_unique_analysis_per_mention_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "kind", "-created_at"], name="ss_analysis_team_kind_recent"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} on mention {self.mention_id} ({self.status})"
