from django.db import models

from posthog.models.utils import UUIDModel


class Project(UUIDModel):
    """
    A visual review project linked to a repository.
    One project per repo per team.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=255, help_text="Display name for the project")

    # GitHub repository info
    github_repo_full_name = models.CharField(
        max_length=255,
        help_text="Full repo name like 'posthog/posthog'",
    )
    github_installation_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="GitHub App installation ID for API access",
    )

    # Optional baseline branch (defaults to main/master)
    default_branch = models.CharField(max_length=255, default="main")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "visual_review_project"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "github_repo_full_name"],
                name="unique_project_per_team_repo",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.github_repo_full_name})"


class Artifact(UUIDModel):
    """
    Content-addressable storage for PNG artifacts.
    Deduplicated by content hash - same image = same artifact.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="artifacts")

    # Content hash is the primary identifier (blake3 or sha256 of bitmap data)
    content_hash = models.CharField(max_length=128, db_index=True)

    # Storage location in object storage (S3 path)
    storage_path = models.CharField(max_length=500)

    # Image metadata
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    size_bytes = models.PositiveIntegerField(help_text="File size in bytes")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "visual_review_artifact"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "content_hash"],
                name="unique_artifact_hash_per_project",
            )
        ]

    def __str__(self) -> str:
        return f"Artifact {self.content_hash[:12]}..."


class Run(UUIDModel):
    """
    A CI run that uploads snapshots for comparison.
    Created when CI posts a manifest.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # Waiting for artifacts
        PROCESSING = "processing", "Processing"  # Diffing in progress
        COMPLETED = "completed", "Completed"  # All diffs done
        FAILED = "failed", "Failed"  # Error during processing

    class Result(models.TextChoices):
        PASS = "pass", "Pass"  # No visual changes
        FAIL = "fail", "Fail"  # Has visual changes
        ERROR = "error", "Error"  # Processing error

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="runs")

    # Git context
    commit_sha = models.CharField(max_length=40)
    branch = models.CharField(max_length=255)
    pr_number = models.PositiveIntegerField(null=True, blank=True)

    # Run type (storybook, playwright, etc.)
    run_type = models.CharField(max_length=50, default="storybook")

    # Status tracking
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    result = models.CharField(max_length=20, choices=Result.choices, null=True, blank=True)

    # Summary stats (populated after diffing)
    total_snapshots = models.PositiveIntegerField(default=0)
    changed_snapshots = models.PositiveIntegerField(default=0)
    new_snapshots = models.PositiveIntegerField(default=0)
    removed_snapshots = models.PositiveIntegerField(default=0)

    # GitHub Check integration
    github_check_run_id = models.BigIntegerField(null=True, blank=True)

    # Approval tracking
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "visual_review_run"
        indexes = [
            models.Index(fields=["project", "branch", "-created_at"]),
            models.Index(fields=["project", "pr_number"]),
            models.Index(fields=["commit_sha"]),
        ]

    def __str__(self) -> str:
        return f"Run {self.id} ({self.branch}@{self.commit_sha[:7]})"


class RunSnapshot(UUIDModel):
    """
    A single snapshot comparison within a run.
    Links current artifact to baseline and stores diff result.
    """

    class DiffStatus(models.TextChoices):
        PENDING = "pending", "Pending"  # Not yet diffed
        UNCHANGED = "unchanged", "Unchanged"  # Identical to baseline
        CHANGED = "changed", "Changed"  # Different from baseline
        NEW = "new", "New"  # No baseline exists
        REMOVED = "removed", "Removed"  # Baseline exists, no current

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="snapshots")

    # Snapshot identifier (e.g., "Button-primary", "LoginPage")
    identifier = models.CharField(max_length=500)

    # Artifact references
    current_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_snapshots",
    )
    baseline_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baseline_snapshots",
    )
    diff_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diff_snapshots",
        help_text="Visual diff image if changed",
    )

    # Diff result
    diff_status = models.CharField(max_length=20, choices=DiffStatus.choices, default=DiffStatus.PENDING)
    diff_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Pixel difference percentage (0.0-100.0)",
    )
    diff_pixel_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of differing pixels",
    )

    # Individual approval (for partial approvals)
    approved = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "visual_review_run_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "identifier"],
                name="unique_snapshot_identifier_per_run",
            )
        ]
        indexes = [
            models.Index(fields=["run", "diff_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.diff_status})"


class Baseline(UUIDModel):
    """
    Stores approved baseline hashes for a project.
    Replaces the .snapshots.yml file in the repo for tracking.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="baselines")

    # Snapshot identifier
    identifier = models.CharField(max_length=500)

    # The approved artifact
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="baselines")

    # Branch context (baselines can be branch-specific)
    branch = models.CharField(max_length=255, default="main")

    # Audit trail
    approved_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "visual_review_baseline"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "identifier", "branch"],
                name="unique_baseline_per_project_identifier_branch",
            )
        ]

    def __str__(self) -> str:
        return f"Baseline: {self.identifier} ({self.branch})"
