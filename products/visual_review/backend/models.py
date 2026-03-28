"""Django models for visual_review."""

from __future__ import annotations

import uuid

from django.db import models

from .facade.enums import ReviewDecision, ReviewState, RunPurpose, RunStatus, RunType, SnapshotResult


class Repo(models.Model):
    """
    A visual review repo tied to a GitHub repository.

    Identity is the GitHub numeric repo ID (survives renames and org transfers).
    repo_full_name is kept for API calls and display, auto-updated on rename detection.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # References posthog.Team in the main database — no FK constraint because
    # this model lives in a separate product database.
    team_id = models.BigIntegerField(db_index=True)

    # GitHub identity: numeric ID is stable, full_name is for API calls + display
    repo_external_id = models.BigIntegerField()
    repo_full_name = models.CharField(max_length=255)

    # Baseline file paths per run type
    # e.g., {"storybook": ".storybook/snapshots.yml", "playwright": "playwright/snapshots.yml"}
    baseline_file_paths = models.JSONField(default=dict, blank=True)

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


class Artifact(models.Model):
    """
    Content-addressed image storage.

    Same hash = same artifact. Deduplicated across all runs in a repo.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="artifacts")
    # Denormalized from repo.team_id for direct team scoping.
    team_id = models.BigIntegerField(db_index=True)

    content_hash = models.CharField(max_length=128, db_index=True)
    storage_path = models.CharField(max_length=1024)

    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["repo", "content_hash"], name="unique_artifact_hash_per_repo"),
        ]

    def __str__(self) -> str:
        return f"{self.content_hash[:12]}..."


class Run(models.Model):
    """
    A visual test run from CI.

    Created when CI posts a manifest. Tracks status through diff processing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="runs")
    # Denormalized from repo.team_id for direct team scoping.
    team_id = models.BigIntegerField(db_index=True)

    status = models.CharField(max_length=20, choices=[(s.value, s.value) for s in RunStatus], default=RunStatus.PENDING)
    run_type = models.CharField(max_length=20, choices=[(t.value, t.value) for t in RunType], default=RunType.OTHER)

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


class RunSnapshot(models.Model):
    """
    A single snapshot within a run.

    Links current captured image to baseline. Stores diff results.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="snapshots")
    # Denormalized from run.team_id for direct team scoping.
    team_id = models.BigIntegerField(db_index=True)

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

    # Diff metrics
    diff_percentage = models.FloatField(null=True, blank=True)
    diff_pixel_count = models.PositiveIntegerField(null=True, blank=True)

    # Review state (human decision, separate from computed result)
    # result = computed diff status (immutable once set)
    # review_state = human decision (can change, e.g., reset on new runs)
    review_state = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in ReviewState],
        default=ReviewState.PENDING,
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
