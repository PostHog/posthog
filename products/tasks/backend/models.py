import os
import re
import json
import uuid
from typing import Literal, Optional

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import DeletedMetaFields, UUIDModel
from posthog.storage import object_storage

from products.tasks.backend.constants import DEFAULT_TRUSTED_DOMAINS

logger = structlog.get_logger(__name__)

LogLevel = Literal["debug", "info", "warn", "error"]


class Task(DeletedMetaFields, models.Model):
    class OriginProduct(models.TextChoices):
        ERROR_TRACKING = "error_tracking", "Error Tracking"
        EVAL_CLUSTERS = "eval_clusters", "Eval Clusters"
        USER_CREATED = "user_created", "User Created"
        SUPPORT_QUEUE = "support_queue", "Support Queue"
        SESSION_SUMMARIES = "session_summaries", "Session Summaries"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_index=False)
    task_number = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    origin_product = models.CharField(max_length=20, choices=OriginProduct.choices)

    # Repository configuration
    github_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"kind": "github"},
        help_text="GitHub integration for this task",
    )

    repository = models.CharField(
        max_length=255, null=True, blank=True
    )  # Format is organization/repo, for example posthog/posthog-js

    json_schema = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="JSON schema for the task. This is used to validate the output of the task.",
    )

    # Video segment clustering fields (for session_summaries origin_product)
    cluster_centroid = ArrayField(
        models.FloatField(),
        null=True,
        blank=True,
        help_text="Embedding centroid for this task's video segment cluster (3072 dimensions)",
    )
    cluster_centroid_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the cluster centroid was last updated",
    )
    priority_score = models.FloatField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Calculated priority score for ranking tasks",
    )
    relevant_user_count = models.IntegerField(
        default=0,
        help_text="Number of unique users affected by this issue",
    )
    occurrence_count = models.IntegerField(
        default=0,
        help_text="Total number of video segment occurrences (cases)",
    )
    last_occurrence_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this issue was last observed in a video segment",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task"
        managed = True

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.repository:
            parts = self.repository.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValidationError({"repository": "Format for repository is organization/repo"})

            self.repository = self.repository.lower()

        if self.task_number is None:
            self._assign_task_number()

        super().save(*args, **kwargs)

    @staticmethod
    def generate_team_prefix(team_name: str) -> str:
        clean_name = "".join(c for c in team_name if c.isalnum())
        uppercase_letters = [c for c in clean_name if c.isupper()]
        if len(uppercase_letters) >= 3:
            return "".join(uppercase_letters[:3])
        return clean_name[:3].upper() if clean_name else "TSK"

    @property
    def slug(self) -> str:
        if self.task_number is None:
            return ""
        prefix = self.generate_team_prefix(self.team.name)
        return f"{prefix}-{self.task_number}"

    @property
    def latest_run(self) -> Optional["TaskRun"]:
        # Use .all() which respects prefetch_related cache, then sort in Python
        # This avoids N+1 queries when tasks are loaded with prefetch_related("runs")
        runs = list(self.runs.all())
        if runs:
            return max(runs, key=lambda r: r.created_at)
        return None

    def _assign_task_number(self) -> None:
        max_task_number = Task.objects.filter(team=self.team).aggregate(models.Max("task_number"))["task_number__max"]
        self.task_number = (max_task_number if max_task_number is not None else -1) + 1

    def create_run(self, environment: Optional["TaskRun.Environment"] = None) -> "TaskRun":
        return TaskRun.objects.create(
            task=self,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            environment=environment or TaskRun.Environment.CLOUD,
        )

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = timezone.now()
        self.save()

    def delete(self, *args, **kwargs):
        raise Exception("Cannot hard delete Task. Use soft_delete() instead.")

    @staticmethod
    def create_and_run(
        *,
        team: Team,
        title: str,
        description: str,
        origin_product: "Task.OriginProduct",
        user_id: int,  # Will be used to validate the tasks feature flag and create a personal api key for interacting with PostHog.
        repository: str,  # Format: "organization/repository", e.g. "posthog/posthog-js"
        create_pr: bool = True,
    ) -> "Task":
        from products.tasks.backend.temporal.client import execute_task_processing_workflow

        created_by = User.objects.get(id=user_id)

        if not created_by:
            raise ValueError(f"User {user_id} does not exist")

        github_integration = Integration.objects.filter(team=team, kind="github").first()

        if not github_integration:
            raise ValueError(f"Team {team.id} does not have a GitHub integration")

        task = Task.objects.create(
            team=team,
            title=title,
            description=description,
            origin_product=origin_product,
            created_by=created_by,
            github_integration=github_integration,
            repository=repository,
        )

        task_run = task.create_run()

        execute_task_processing_workflow(
            task_id=str(task.id),
            run_id=str(task_run.id),
            team_id=task.team.id,
            user_id=user_id,
            create_pr=create_pr,
        )

        return task


class TaskRun(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        QUEUED = "queued", "Queued"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Environment(models.TextChoices):
        LOCAL = "local", "Local"
        CLOUD = "cloud", "Cloud"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="runs")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    branch = models.CharField(max_length=255, blank=True, null=True, help_text="Branch name for the run")
    environment = models.CharField(
        max_length=10, choices=Environment.choices, default=Environment.CLOUD, help_text="Execution environment"
    )

    # Stage tracking
    stage = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Current stage for this run (e.g., 'research', 'plan', 'build')",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)

    error_message = models.TextField(blank=True, null=True, help_text="Error message if execution failed")

    # This is a structured output of the run. This is used to store the PR URL, commit SHA, etc.
    output = models.JSONField(
        blank=True,
        null=True,
        help_text="Run output data (e.g., PR URL, commit SHA, etc.)",
    )

    # Artifact manifest describing files uploaded to S3 for this run.
    artifacts = models.JSONField(
        blank=True,
        default=list,
        help_text="List of artifacts uploaded to S3 for this run.",
    )

    # Store intermediate run state in this field. This is used to resume the run if it fails, or to provide context throughout the run.
    state = models.JSONField(
        default=dict,
        blank=True,
        help_text="Run state data for resuming or tracking execution state",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_task_run"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run for {self.task.title} - {self.get_status_display()}"

    @property
    def log_url(self) -> str:
        """Generate S3 path for this run's logs"""
        tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return f"{tasks_folder}/logs/team_{self.team_id}/task_{self.task_id}/run_{self.id}.jsonl"

    def get_artifact_s3_prefix(self) -> str:
        """Base prefix for storing artifacts in S3"""
        tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return f"{tasks_folder}/artifacts/team_{self.team_id}/task_{self.task_id}/run_{self.id}"

    def append_log(self, entries: list[dict]):
        """Append log entries to S3 storage."""
        existing_content = object_storage.read(self.log_url, missing_ok=True) or ""
        is_new_file = not existing_content

        new_lines = "\n".join(json.dumps(entry) for entry in entries)
        content = existing_content + ("\n" if existing_content else "") + new_lines

        object_storage.write(self.log_url, content)

        if is_new_file:
            try:
                object_storage.tag(
                    self.log_url,
                    {
                        "ttl_days": "30",
                        "team_id": str(self.team_id),
                    },
                )
            except Exception as e:
                logger.warning(
                    "task_run.failed_to_tag_logs",
                    task_run_id=str(self.id),
                    log_url=self.log_url,
                    error=str(e),
                )

    def mark_completed(self):
        """Mark the progress as completed."""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    def mark_failed(self, error: str):
        """Mark the progress as failed with an error message."""
        self.status = self.Status.FAILED
        self.error_message = error
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at"])

    def emit_console_event(self, level: LogLevel, message: str) -> None:
        """Emit a console-style log event in ACP notification format."""
        event = {
            "type": "notification",
            "timestamp": timezone.now().isoformat(),
            "notification": {
                "jsonrpc": "2.0",
                "method": "_posthog/console",
                "params": {
                    "sessionId": str(self.id),
                    "level": level,
                    "message": message,
                },
            },
        }
        self.append_log([event])

    def emit_sandbox_output(self, stdout: str, stderr: str, exit_code: int) -> None:
        """Emit sandbox execution output as ACP notification."""
        event = {
            "type": "notification",
            "timestamp": timezone.now().isoformat(),
            "notification": {
                "jsonrpc": "2.0",
                "method": "_posthog/sandbox_output",
                "params": {
                    "sessionId": str(self.id),
                    "stdout": stdout,
                    "stderr": stderr,
                    "exitCode": exit_code,
                },
            },
        }
        self.append_log([event])

    def delete(self, *args, **kwargs):
        raise Exception("Cannot delete TaskRun. Task runs are immutable records.")


class SandboxSnapshot(UUIDModel):
    """Tracks sandbox snapshots used for sandbox environments in tasks."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETE = "complete", "Complete"
        ERROR = "error", "Error"

    integration = models.ForeignKey(
        Integration,
        on_delete=models.SET_NULL,
        related_name="snapshots",
        null=True,
        blank=True,
    )

    external_id = models.CharField(
        max_length=255, blank=True, help_text="Snapshot ID from external provider.", unique=True
    )

    repos = ArrayField(
        models.CharField(max_length=255),
        default=list,
        help_text="List of repositories in format 'org/repo'",
    )

    metadata = models.JSONField(default=dict, blank=True, help_text="Additional metadata for the snapshot.")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_sandbox_snapshot"
        indexes = [
            models.Index(fields=["integration", "status", "-created_at"]),
        ]

    def __str__(self):
        repo_count = len(self.repos)
        return f"Snapshot {self.external_id} ({self.get_status_display()}, {repo_count} repos)"

    def is_complete(self) -> bool:
        return self.status == self.Status.COMPLETE

    def has_repo(self, repo: str) -> bool:
        repo_lower = repo.lower()
        return any(r.lower() == repo_lower for r in self.repos)

    def has_repos(self, repos: list[str]) -> bool:
        return all(self.has_repo(repo) for repo in repos)

    def update_status(self, status: Status):
        self.status = status
        self.save(update_fields=["status"])

    @classmethod
    def get_latest_snapshot_for_integration(cls, integration_id: int) -> Optional["SandboxSnapshot"]:
        return (
            cls.objects.filter(
                integration_id=integration_id,
                status=cls.Status.COMPLETE,
            )
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def get_latest_snapshot_with_repos(
        cls, integration_id: int, required_repos: list[str]
    ) -> Optional["SandboxSnapshot"]:
        snapshots = cls.objects.filter(
            integration_id=integration_id,
            status=cls.Status.COMPLETE,
        ).order_by("-created_at")

        for snapshot in snapshots:
            if snapshot.has_repos(required_repos):
                return snapshot
        return None

    def delete(self, *args, **kwargs):
        if self.external_id:
            from products.tasks.backend.services.sandbox import Sandbox

            if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET") and not settings.TEST:
                try:
                    Sandbox.delete_snapshot(self.external_id)
                except Exception as e:
                    raise Exception(
                        f"Failed to delete external snapshot {self.external_id}: {str(e)}. "
                        f"The database record has not been deleted."
                    ) from e

        super().delete(*args, **kwargs)


class SandboxEnvironment(UUIDModel):
    """Configuration for sandbox execution environments including network access and secrets."""

    class NetworkAccessLevel(models.TextChoices):
        TRUSTED = "trusted", "Trusted"
        FULL = "full", "Full"
        CUSTOM = "custom", "Custom"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    name = models.CharField(max_length=255)

    network_access_level = models.CharField(
        max_length=20,
        choices=NetworkAccessLevel.choices,
        default=NetworkAccessLevel.FULL,  # NOTE: Default should be TRUSTED once we have an egress proxy in place
    )

    allowed_domains = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        help_text="List of allowed domains for custom network access",
    )

    include_default_domains = models.BooleanField(
        default=False,
        help_text="Whether to include default trusted domains (GitHub, npm, PyPI)",
    )

    repositories = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        help_text="List of repositories this environment applies to (format: org/repo)",
    )

    environment_variables = EncryptedJSONStringField(
        default=dict,
        blank=True,
        null=True,
        help_text="Encrypted environment variables for sandbox execution",
    )

    private = models.BooleanField(
        default=True,
        help_text="If true, only the creator can see this environment. Otherwise visible to whole team.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_sandbox_environment"
        indexes = [
            models.Index(fields=["team", "created_by"]),
        ]

    def __str__(self):
        return self.name

    @staticmethod
    def is_valid_env_var_key(key: str) -> bool:
        if not key:
            return False
        pattern = r"^[A-Za-z_][A-Za-z0-9_]*$"
        return bool(re.match(pattern, key))

    def get_effective_domains(self) -> list[str]:
        if self.network_access_level == self.NetworkAccessLevel.FULL:
            return []

        if self.network_access_level == self.NetworkAccessLevel.TRUSTED:
            return DEFAULT_TRUSTED_DOMAINS.copy()

        if self.network_access_level == self.NetworkAccessLevel.CUSTOM:
            domains = list(self.allowed_domains)
            if self.include_default_domains:
                for domain in DEFAULT_TRUSTED_DOMAINS:
                    if domain not in domains:
                        domains.append(domain)
            return domains

        return []


class TaskReference(models.Model):
    """Links a reference (video segment, error, etc.) to a Task.

    Each record represents one occurrence that contributed to or matches a Task's cluster.
    Used for tracking cases and calculating priority.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="references")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # Reference identification
    session_id = models.CharField(max_length=255)
    start_time = models.DateTimeField(null=False, blank=False)
    end_time = models.DateTimeField(null=True, blank=True)

    # User tracking for relevant_user_count
    distinct_id = models.CharField(max_length=255)

    # Reference content
    content = models.TextField(
        blank=True,
        help_text="The reference description text",
    )

    # Clustering metadata
    distance_to_centroid = models.FloatField(
        null=True,
        blank=True,
        help_text="Cosine distance from this reference to the task's cluster centroid",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_task_reference"
        indexes = [
            models.Index(fields=["task_id", "session_id"]),
            models.Index(fields=["team_id", "session_id"]),
            models.Index(fields=["distinct_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["task_id", "session_id", "start_time", "end_time"],
                name="unique_task_reference",
            )
        ]

    def __str__(self):
        return f"Reference {self.session_id}:{self.start_time}-{self.end_time} -> Task {self.task_id}"
