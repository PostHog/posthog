"""Django models for visual_review."""

from __future__ import annotations

import uuid

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel

from .facade.enums import (
    ActorType,
    ClassificationReason,
    ReviewDecision,
    ReviewState,
    RunPurpose,
    RunStatus,
    RunType,
    SnapshotResult,
    ToleratedReason,
)


class Repo(ProductTeamModel):
    """
    A visual review repo tied to a GitHub repository.

    Identity is the GitHub numeric repo ID (survives renames and org transfers).
    repo_full_name is kept for API calls and display, auto-updated on rename detection.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # GitHub identity: numeric ID is stable, full_name is for API calls + display
    repo_external_id = models.BigIntegerField()
    repo_full_name = models.CharField(max_length=255)

    # Baseline file paths per run type
    # e.g., {"storybook": ".storybook/snapshots.yml", "playwright": "playwright/snapshots.yml"}
    baseline_file_paths = models.JSONField(default=dict, blank=True)

    # Whether to post a PR comment prompting reviewers when visual changes are detected.
    # Default off — teams opt in when they want commenting, and it stays off during
    # auto-approve rollout phases where comments would be noise.
    enable_pr_comments = models.BooleanField(default=False)

    # HMAC signing keys for baseline hash verification: {kid: secret_hex}
    # Supports key rotation — new signatures use the latest key, verification
    # accepts any valid kid. Auto-generated on first use.
    signing_keys = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "repo_external_id"], name="unique_repo_per_team"),
        ]

    def __str__(self) -> str:
        return self.repo_full_name

    def get_active_signing_key(self) -> tuple[str, str]:
        """Return ``(kid, secret_hex)`` for the active signing key.

        Auto-generates a key on first access and persists it.
        """
        from .signing import generate_signing_key

        keys: dict[str, str] = self.signing_keys or {}
        if keys:
            kid = max(keys)  # lexicographic latest
            return kid, keys[kid]

        kid, secret_hex = generate_signing_key()
        self.signing_keys = {kid: secret_hex}
        self.save(update_fields=["signing_keys"])
        return kid, secret_hex


class Artifact(ProductTeamModel):
    """
    Content-addressed image storage.

    Same hash = same artifact. Deduplicated across all runs in a repo.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="artifacts")

    content_hash = models.CharField(max_length=128, db_index=True)
    storage_path = models.CharField(max_length=1024)

    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)

    thumbnail = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["repo", "content_hash"], name="unique_artifact_hash_per_repo"),
        ]

    def __str__(self) -> str:
        return f"{self.content_hash[:12]}..."


class Run(ProductTeamModel):
    """
    A visual test run from CI.

    Created when CI posts a manifest. Tracks status through diff processing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="runs")

    status = models.CharField(max_length=20, choices=[(s.value, s.value) for s in RunStatus], default=RunStatus.PENDING)
    run_type = models.CharField(max_length=64, default=RunType.OTHER)

    # Git context
    commit_sha = models.CharField(max_length=40)
    branch = models.CharField(max_length=255)
    pr_number = models.PositiveIntegerField(null=True, blank=True)

    # Purpose and review
    purpose = models.CharField(
        max_length=20, choices=[(p.value, p.value) for p in RunPurpose], default=RunPurpose.REVIEW
    )
    review_decision = models.CharField(
        max_length=20, choices=[(d.value, d.value) for d in ReviewDecision], default=ReviewDecision.PENDING
    )
    # Legacy — derived from review_decision, kept for backward compat during migration
    approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    # References posthog.User in the main database — plain integer, no FK.
    approved_by_id = models.BigIntegerField(null=True, blank=True)

    # Summary (populated after diff processing)
    total_snapshots = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    new_count = models.PositiveIntegerField(default=0)
    removed_count = models.PositiveIntegerField(default=0)
    tolerated_match_count = models.PositiveIntegerField(default=0)

    error_message = models.TextField(blank=True)

    # Supersession: set when a newer run is created for the same (repo, branch, run_type).
    # NULL = this is the latest run for its group. Non-NULL = superseded, points to the replacing run.
    superseded_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="supersedes"
    )

    # Flexible metadata (not indexed)
    # e.g., {"pr_title": "...", "base_branch": "main", "ci_job_url": "..."}
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["repo", "branch", "run_type", "superseded_by"], name="run_branch_type_current"),
            models.Index(fields=["repo", "pr_number"], name="run_repo_pr"),
            models.Index(fields=["commit_sha"], name="run_commit_sha"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "branch", "run_type"],
                condition=models.Q(superseded_by__isnull=True),
                name="unique_latest_run_per_group",
            ),
        ]

    def __str__(self) -> str:
        return f"Run {self.id} ({self.status})"


class RunSnapshot(ProductTeamModel):
    """
    A single snapshot within a run.

    Links current captured image to baseline. Stores diff results.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="snapshots")

    identifier = models.CharField(max_length=512)

    # Hash values (stored for linking artifacts after upload)
    current_hash = models.CharField(max_length=128, blank=True)
    baseline_hash = models.CharField(max_length=128, blank=True)

    # Dimensions from manifest (used for artifact creation during complete)
    current_width = models.PositiveIntegerField(null=True, blank=True)
    current_height = models.PositiveIntegerField(null=True, blank=True)

    # Current artifact (from this CI run)
    current_artifact = models.ForeignKey(
        Artifact, on_delete=models.SET_NULL, null=True, blank=True, related_name="current_snapshots"
    )

    # Baseline artifact (from .snapshots.yml)
    baseline_artifact = models.ForeignKey(
        Artifact, on_delete=models.SET_NULL, null=True, blank=True, related_name="baseline_snapshots"
    )

    # Diff artifact (generated by diff engine)
    diff_artifact = models.ForeignKey(
        Artifact, on_delete=models.SET_NULL, null=True, blank=True, related_name="diff_snapshots"
    )

    result = models.CharField(
        max_length=20, choices=[(r.value, r.value) for r in SnapshotResult], default=SnapshotResult.UNCHANGED
    )
    # Why this snapshot was classified as UNCHANGED (empty for CHANGED/NEW/REMOVED)
    classification_reason = models.CharField(
        max_length=20, choices=[(r.value, r.value) for r in ClassificationReason], blank=True, default=""
    )
    # Set when classification used a tolerated alternate hash
    tolerated_hash_match = models.ForeignKey(
        "ToleratedHash", on_delete=models.SET_NULL, null=True, blank=True, related_name="matched_snapshots"
    )

    # Frozen at run finalization — reflects quarantine policy at that point in time
    is_quarantined = models.BooleanField(default=False)

    # Diff metrics. `diff_percentage` always means "fraction of pixels that
    # differ" — the previous behavior where the SSIM tier overwrote this with
    # SSIM dissimilarity is gone (split into `ssim_score` + `change_kind`
    # below). Pre-split rows have been backfilled accordingly: SSIM-tier
    # rows have `diff_percentage = NULL`, `ssim_score` derived from the
    # original dissimilarity, and `change_kind = 'structural'`.
    diff_percentage = models.FloatField(null=True, blank=True)
    diff_pixel_count = models.PositiveIntegerField(null=True, blank=True)
    # SSIM score (0.0–1.0). 1.0 = identical, lower = more structurally
    # different. Populated for every diffed snapshot regardless of which
    # tier classified it.
    ssim_score = models.FloatField(null=True, blank=True)
    # Categorical: see ChangeKind enum. Empty for snapshots that haven't
    # been diffed (NEW, REMOVED, exact-match UNCHANGED).
    change_kind = models.CharField(max_length=24, blank=True, default="")
    # System-computed metadata produced by the diff pipeline (not the
    # uploader's `metadata` field above, which is for ingestion-time
    # context like browser/viewport). Storage is JSONB but the Python
    # shape is governed by `DiffMetadata` in `diff_metadata.py` — all
    # writes go through `.model_dump()` and reads through
    # `.model_validate()`. Currently holds `cluster_summary`; future
    # additions like `engine_version` land alongside without a schema
    # migration.
    diff_metadata = models.JSONField(default=dict, blank=True)

    # Review state — only set on actionable snapshots (CHANGED, NEW, REMOVED).
    # Empty for unchanged snapshots that don't need review.
    review_state = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in ReviewState],
        blank=True,
        default="",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    # References posthog.User in the main database — plain integer, no FK.
    reviewed_by_id = models.BigIntegerField(null=True, blank=True)
    review_comment = models.TextField(blank=True)  # For rejection reasons or notes
    # Hash that was approved (specific to approval action)
    approved_hash = models.CharField(max_length=128, blank=True)

    # Flexible metadata (not indexed)
    # e.g., {"browser": "chrome", "viewport": "desktop", "is_flaky": true, "is_critical": true, "page_group": "Checkout"}
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "identifier"], name="unique_snapshot_identifier_per_run"),
        ]
        indexes = [
            models.Index(fields=["run", "result"], name="snapshot_run_result"),
            models.Index(fields=["run", "review_state"], name="snapshot_run_review_state"),
            models.Index(fields=["identifier"], name="snapshot_identifier"),
            models.Index(fields=["current_hash"], name="snapshot_current_hash"),
            models.Index(fields=["baseline_hash"], name="snapshot_baseline_hash"),
        ]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.result})"


class ToleratedHash(ProductTeamModel):
    """
    Previously seen alternate hashes that were determined acceptable for a
    specific baseline and snapshot identifier, allowing future runs to skip
    expensive diff processing.

    Keyed by (repo, identifier, baseline_hash, content_hash) — when the
    canonical baseline changes, old tolerations expire naturally because
    baseline_hash no longer matches.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="tolerated_hashes")

    identifier = models.CharField(max_length=512)
    baseline_hash = models.CharField(max_length=128)
    alternate_hash = models.CharField(max_length=128)

    reason = models.CharField(
        max_length=20,
        choices=[(r.value, r.value) for r in ToleratedReason],
    )

    # Which run caused this toleration to be recorded
    source_run = models.ForeignKey(Run, on_delete=models.SET_NULL, null=True, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)

    diff_percentage = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "identifier", "baseline_hash", "alternate_hash"],
                name="unique_tolerated_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["repo", "identifier", "baseline_hash"], name="tolerated_lookup"),
        ]

    def __str__(self) -> str:
        return f"{self.identifier} {self.alternate_hash[:12]}... ({self.reason})"


class QuarantinedIdentifier(ProductTeamModel):
    """
    Tracks quarantine events for snapshot identifiers.

    Each row is a quarantine event — multiple rows per identifier form
    a history. The active quarantine is the latest row where expires_at
    is NULL or in the future. Unquarantining sets expires_at = now()
    rather than deleting, preserving the audit trail.

    Quarantined snapshots are still captured, classified, and diffed
    (for metrics), but excluded from the gate at run finalization.
    The decision is frozen on RunSnapshot.is_quarantined so historical
    runs remain stable even if quarantine policy changes later.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="quarantined_identifiers")

    identifier = models.CharField(max_length=512)
    run_type = models.CharField(max_length=64)
    reason = models.CharField(max_length=255)
    source = models.CharField(
        max_length=10,
        choices=[(a.value, a.value) for a in ActorType],
        default=ActorType.HUMAN,
    )

    expires_at = models.DateTimeField(null=True, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["repo", "run_type", "identifier"], name="quarantine_lookup"),
        ]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.reason[:40]})"
