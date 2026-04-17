import os
import re
import json
import uuid
import string
import secrets
from typing import TYPE_CHECKING, Any, Literal, Optional

from django.db.models.signals import post_save
from django.dispatch import receiver

from pydantic import BaseModel

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import DeletedMetaFields, UUIDModel
from posthog.storage import object_storage
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.constants import DEFAULT_TRUSTED_DOMAINS
from products.tasks.backend.stream.redis_stream import publish_task_run_stream_event

logger = structlog.get_logger(__name__)

LogLevel = Literal["debug", "info", "warn", "error"]


def resolve_schema(schema: type[BaseModel] | dict) -> dict:
    if isinstance(schema, dict):
        return schema
    return schema.model_json_schema()


class Task(DeletedMetaFields, models.Model):
    class OriginProduct(models.TextChoices):
        ERROR_TRACKING = "error_tracking", "Error Tracking"
        EVAL_CLUSTERS = "eval_clusters", "Eval Clusters"
        USER_CREATED = "user_created", "User Created"
        SLACK = "slack", "Slack"
        SUPPORT_QUEUE = "support_queue", "Support Queue"
        SESSION_SUMMARIES = "session_summaries", "Session Summaries"
        # Unlike the others (which indicate direct creation from that product, e.g. a "fix this error" button),
        # signal report tasks originate indirectly via signals from other products.
        SIGNAL_REPORT = "signal_report", "Signal Report"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_index=False)
    task_number = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=255)
    title_manually_set = models.BooleanField(default=False)
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

    # DEPRECATED - do not use
    signal_report = models.ForeignKey(
        "signals.SignalReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task",
        db_index=False,
    )

    json_schema = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="JSON schema for the task. This is used to validate the output of the task.",
    )

    internal = models.BooleanField(
        default=False,
        help_text="If true, this task is for internal use and should not be exposed to end users.",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    ci_prompt = models.TextField(
        blank=True,
        null=True,
        help_text="Custom prompt for CI fixes. If blank, a default prompt will be used.",
    )

    class Meta:
        db_table = "posthog_task"
        managed = True
        indexes = [
            models.Index(fields=["signal_report"], name="posthog_task_signal_report_idx"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        if self.repository:
            parts = self.repository.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValidationError({"repository": "Format for repository is organization/repo"})

            self.repository = self.repository.lower()

        if self.task_number is None:
            self._assign_task_number()

        super().save(*args, **kwargs)

        if is_new:
            self._track_task_created()

    def capture_event(self, event: str, properties: dict | None = None) -> None:
        try:
            distinct_id = (
                str(self.created_by.distinct_id) if self.created_by_id and self.created_by else str(self.team.uuid)
            )
            all_properties = {
                "task_id": str(self.id),
                "team_id": self.team_id,
                "title": self.title,
                "description": self.description[:500] if self.description else "",
                "origin_product": self.origin_product,
                "repository": self.repository,
            }
            if properties:
                all_properties.update(properties)
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event=event,
                properties=all_properties,
                groups=groups(team=self.team),
            )
        except Exception as e:
            logger.warning("task.capture_event_failed", analytics_event=event, error=str(e))

    def _track_task_created(self) -> None:
        self.capture_event(
            "task_created",
            {"has_json_schema": self.json_schema is not None},
        )

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

    def create_run(
        self,
        environment: Optional["TaskRun.Environment"] = None,
        mode: str = "background",
        extra_state: dict | None = None,
        branch: str | None = None,
    ) -> "TaskRun":
        state: dict = {"mode": mode}
        if extra_state:
            state.update({k: v for k, v in extra_state.items() if k != "mode"})
        is_resume = bool((extra_state or {}).get("resume_from_run_id"))
        has_pending = bool((extra_state or {}).get("pending_message"))
        task_run = TaskRun.objects.create(
            task=self,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            **({"environment": environment} if environment else {}),
            state=state,
            branch=branch,
        )
        task_run.publish_stream_state_event()
        self.capture_event(
            "task_run_created",
            {
                "run_id": str(task_run.id),
                "mode": mode,
                "environment": task_run.environment,
                "is_resume": is_resume,
                "has_pending_message": has_pending,
            },
        )
        return task_run

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = timezone.now()
        self.save()
        self.capture_event(
            "task_deleted",
            {"duration_seconds": round((timezone.now() - self.created_at).total_seconds(), 1)},
        )

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
        repository: str | None = None,  # Format: "organization/repository", e.g. "posthog/posthog-js"
        create_pr: bool = True,
        mode: str = "background",
        slack_thread_context: Optional["SlackThreadContext"] = None,
        slack_thread_url: str | None = None,
        start_workflow: bool = True,
        posthog_mcp_scopes: PosthogMcpScopes = "full",
        branch: str | None = None,
        signal_report_id: str | None = None,
        sandbox_environment_id: str | None = None,
        internal: bool = False,
        output_schema: type[BaseModel] | dict | None = None,
    ) -> "Task":
        from products.tasks.backend.temporal.client import execute_task_processing_workflow

        created_by = User.objects.get(id=user_id)

        from products.tasks.backend.services.sandbox import is_public_sandbox_repo

        github_integration = None
        if repository:
            github_integration = Integration.objects.filter(team=team, kind="github").first()
            if not github_integration and not is_public_sandbox_repo(repository):
                raise ValueError(f"Team {team.id} does not have a GitHub integration")

        sandbox_env = None
        if sandbox_environment_id is not None:
            sandbox_env = SandboxEnvironment.objects.filter(id=sandbox_environment_id, team=team).first()
            if not sandbox_env:
                raise ValueError(f"Invalid sandbox_environment_id: {sandbox_environment_id}")

        task = Task.objects.create(
            team=team,
            title=title,
            description=description,
            origin_product=origin_product,
            created_by=created_by,
            github_integration=github_integration,
            repository=repository,
            internal=internal,
            json_schema=resolve_schema(output_schema) if output_schema else None,
            **({"signal_report_id": signal_report_id} if signal_report_id else {}),
        )

        extra_state: dict[str, str] = {}
        if slack_thread_url:
            extra_state["slack_thread_url"] = slack_thread_url
        if slack_thread_context:
            extra_state["interaction_origin"] = "slack"

        if sandbox_env is not None:
            extra_state["sandbox_environment_id"] = str(sandbox_env.id)

        task_run = task.create_run(mode=mode, extra_state=extra_state or None, branch=branch)

        if start_workflow:
            execute_task_processing_workflow(
                task_id=str(task.id),
                run_id=str(task_run.id),
                team_id=task.team.id,
                user_id=user_id,
                create_pr=create_pr,
                slack_thread_context=slack_thread_context,
                posthog_mcp_scopes=posthog_mcp_scopes,
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
        max_length=10,
        choices=Environment.choices,
        default=Environment.CLOUD,
        help_text="Execution environment",
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
    def mode(self) -> str:
        """Get the execution mode from state. Defaults to 'background'."""
        return (self.state or {}).get("mode", "background")

    def get_sandbox_environment(self) -> Optional["SandboxEnvironment"]:
        """Resolve the SandboxEnvironment for this run, scoped to team and respecting privacy.

        Private environments are only accessible if the task creator matches the
        environment creator. If either created_by is null, private environments
        are not accessible.
        """
        env_id = (self.state or {}).get("sandbox_environment_id")
        if not env_id:
            return None
        env = SandboxEnvironment.objects.filter(id=env_id, team_id=self.team_id).first()
        if not env:
            return None
        if env.private:
            task_user_id = self.task.created_by_id
            if not task_user_id or env.created_by_id != task_user_id:
                return None
        return env

    @staticmethod
    def get_workflow_id(task_id: str | uuid.UUID, run_id: str | uuid.UUID) -> str:
        """Get the Temporal workflow ID for a task run."""
        return f"task-processing-{task_id}-{run_id}"

    @property
    def workflow_id(self) -> str:
        """Get the Temporal workflow ID for this task run."""
        return self.get_workflow_id(self.task_id, self.id)

    def heartbeat_workflow(self) -> None:
        from django.core.cache import cache

        cache_key = f"tasks:task_run:heartbeat:{self.id}"
        if not cache.add(cache_key, True, timeout=60):
            return

        import asyncio

        from posthog.temporal.common.client import sync_connect

        from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

        try:
            client = sync_connect()
            handle = client.get_workflow_handle(self.workflow_id)
            asyncio.run(handle.signal(ProcessTaskWorkflow.heartbeat))
        except Exception as e:
            logger.warning("task_run.heartbeat_failed", task_run_id=str(self.id), error=str(e))

    @property
    def log_url(self) -> str:
        """Generate S3 path for this run's logs"""
        tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return f"{tasks_folder}/logs/team_{self.team_id}/task_{self.task_id}/run_{self.id}.jsonl"

    def get_artifact_s3_prefix(self) -> str:
        """Base prefix for storing artifacts in S3"""
        tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return f"{tasks_folder}/artifacts/team_{self.team_id}/task_{self.task_id}/run_{self.id}"

    @staticmethod
    def _is_agent_message_chunk(entry: dict) -> bool:
        """Check if an entry is an agent_message_chunk event."""
        notification = entry.get("notification", {})
        if not isinstance(notification, dict):
            return False
        if notification.get("method") != "session/update":
            return False
        params = notification.get("params", {})
        update = params.get("update", {}) if isinstance(params, dict) else {}
        return update.get("sessionUpdate") == "agent_message_chunk" if isinstance(update, dict) else False

    def append_log(self, entries: list[dict]):
        """Append log entries to S3 storage."""
        entries = [e for e in entries if not self._is_agent_message_chunk(e)]
        if not entries:
            return

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

    def capture_event(self, event: str, properties: dict | None = None) -> None:
        try:
            distinct_id = (
                str(self.task.created_by.distinct_id)
                if self.task.created_by_id and self.task.created_by
                else str(self.team.uuid)
            )
            all_properties: dict = {
                "task_id": str(self.task_id),
                "run_id": str(self.id),
                "team_id": self.team_id,
                "repository": self.task.repository,
                "origin_product": self.task.origin_product,
                "title": self.task.title,
                "signal_report_id": str(self.task.signal_report_id) if self.task.signal_report_id else None,
                "environment": self.environment,
                "mode": self.mode,
            }
            if properties:
                all_properties.update(properties)
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event=event,
                properties=all_properties,
                groups=groups(team=self.team),
            )
        except Exception as e:
            logger.warning("task_run.capture_event_failed", analytics_event=event, error=str(e))

    def _duration_seconds(self) -> float:
        if self.completed_at and self.created_at:
            return round((self.completed_at - self.created_at).total_seconds(), 1)
        return 0.0

    def mark_completed(self):
        """Mark the progress as completed."""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])
        self.publish_stream_state_event()
        self.capture_event(
            "task_run_completed",
            {"duration_seconds": self._duration_seconds()},
        )

    def track_structured_result(self):
        """Track a structured result event with properties from the run output."""
        if not self.output:
            return

        try:
            self.capture_event("task_run_structured_result", {"result": self.output})
        except Exception as e:
            logger.warning(
                "task_run.track_structured_result_failed",
                task_run_id=str(self.id),
                error=str(e),
            )

    def mark_failed(self, error: str):
        """Mark the progress as failed with an error message."""
        self.status = self.Status.FAILED
        self.error_message = error
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at"])
        self.publish_stream_state_event()
        self.capture_event(
            "task_run_failed",
            {
                "error_message": error[:500],
                "duration_seconds": self._duration_seconds(),
            },
        )

    def build_stream_state_event(self) -> dict[str, Any]:
        return {
            "type": "task_run_state",
            "run_id": str(self.id),
            "task_id": str(self.task_id),
            "status": self.status,
            "stage": self.stage,
            "output": self.output,
            "branch": self.branch,
            "error_message": self.error_message,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def publish_stream_event(self, event: dict[str, Any]) -> None:
        publish_task_run_stream_event(str(self.id), event)

    def publish_stream_state_event(self) -> None:
        self.publish_stream_event(self.build_stream_state_event())

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
        self.publish_stream_event(event)

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
        self.publish_stream_event(event)

    @property
    def is_terminal(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.FAILED, self.Status.CANCELLED}

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
        max_length=255,
        blank=True,
        help_text="Snapshot ID from external provider.",
        unique=True,
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

    internal = models.BooleanField(
        default=False,
        help_text="If true, this environment is for internal use (e.g. signals pipeline) and should not be exposed to end users.",
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


class CodeInvite(UUIDModel):
    """Invite codes for PostHog Code access."""

    code = models.CharField(max_length=50, unique=True, db_index=True, blank=True)
    max_redemptions = models.PositiveIntegerField(default=1, help_text="Maximum number of redemptions. 0 = unlimited.")
    redemption_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Optional expiration date.")
    description = models.TextField(blank=True, help_text="Internal admin note.")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_code_invites"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_code_invite"

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            alphabet = string.ascii_uppercase + string.digits
            for attempt in range(10):
                self.code = "".join(secrets.choice(alphabet) for _ in range(8))
                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    if attempt == 9:
                        raise
            return
        super().save(*args, **kwargs)

    @property
    def is_redeemable(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        if self.max_redemptions > 0 and self.redemption_count >= self.max_redemptions:
            return False
        return True


class CodeInviteRedemption(UUIDModel):
    """Tracks each redemption of a PostHog Code invite."""

    invite_code = models.ForeignKey(CodeInvite, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE)
    organization = models.ForeignKey("posthog.Organization", on_delete=models.SET_NULL, null=True, blank=True)
    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_code_invite_redemption"
        unique_together = [("invite_code", "user")]

    def __str__(self):
        return f"{self.user} redeemed {self.invite_code}"


@receiver(post_save, sender=TaskRun)
def track_task_run_completion(sender, instance: TaskRun, created: bool, **kwargs):
    try:
        if (
            not created
            and instance.status == TaskRun.Status.COMPLETED
            and instance.output
            and instance.task.json_schema
        ):
            instance.track_structured_result()
    except Exception as e:
        logger.warning(
            "task_run.track_task_run_completion_failed",
            task_run_id=str(instance.id),
            error=str(e),
        )
