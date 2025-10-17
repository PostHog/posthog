import os
import uuid
from typing import Optional

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.utils import timezone

from asgiref.sync import async_to_sync

from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel

from products.tasks.backend.agents import get_agent_by_id
from products.tasks.backend.lib.templates import DEFAULT_WORKFLOW_TEMPLATE, WorkflowTemplate


class TaskWorkflow(models.Model):
    """Defines a configurable workflow with stages and transition rules."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255, help_text="Human-readable name for this workflow")
    description = models.TextField(blank=True, help_text="Description of the workflow purpose")
    color = models.CharField(max_length=7, default="#3b82f6", help_text="Hex color for UI display")
    is_default = models.BooleanField(default=False, help_text="Whether this is the default workflow for new tasks")
    is_active = models.BooleanField(default=True, help_text="Whether this workflow is currently active")
    version = models.IntegerField(default=1, help_text="Version number for tracking workflow changes")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_workflow"
        unique_together = [("team", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.team.name})"

    @property
    def active_stages(self):
        return self.stages.filter(is_archived=False)

    def migrate_tasks_to_workflow(self, target_workflow: "TaskWorkflow") -> int:
        """Migrate all tasks from this workflow to another workflow. Returns number of tasks updated."""

        if target_workflow.id == self.id:
            return 0

        if self.team_id != target_workflow.team_id:
            raise ValueError("Source and target workflows must belong to the same team")

        current_workflow_tasks_qs = self.tasks.all()

        if not current_workflow_tasks_qs.exists():
            return 0

        # Prefetch target stages once; preserve deterministic fallback using stage position ordering
        active_stages = list(target_workflow.stages.filter(is_archived=False).order_by("position"))

        stages_by_key = {stage.key: stage for stage in active_stages}

        fallback_stage = active_stages[0] if active_stages else None

        updated_tasks = []

        for task in current_workflow_tasks_qs:
            if task.workflow_id != target_workflow.id:
                task.workflow = target_workflow
                updated_tasks.append(task)

        # Update task runs to use matching stages from the target workflow
        if len(active_stages) > 0:
            task_runs = TaskRun.objects.filter(task__in=current_workflow_tasks_qs).select_related("current_stage")
            updated_runs = []

            for task_run in task_runs:
                next_stage = None

                if task_run.current_stage and task_run.current_stage.key in stages_by_key:
                    next_stage = stages_by_key[task_run.current_stage.key]
                else:
                    next_stage = fallback_stage

                if task_run.current_stage != next_stage:
                    task_run.current_stage = next_stage
                    updated_runs.append(task_run)

            if len(updated_runs) > 0:
                TaskRun.objects.bulk_update(updated_runs, ["current_stage"])

        if len(updated_tasks) > 0:
            Task.objects.bulk_update(updated_tasks, ["workflow"])

        return len(updated_tasks)

    def unassign_tasks(self):
        tasks = self.tasks.all()

        updated_tasks = []

        for task in tasks:
            task.workflow = None
            updated_tasks.append(task)

        # Clear current_stage from all task runs
        TaskRun.objects.filter(task__in=tasks).update(current_stage=None)

        Task.objects.bulk_update(updated_tasks, ["workflow"])

    def deactivate_safely(self):
        """Deactivate workflow and move tasks to team default."""

        if not self.is_active:
            return

        if self.is_default:
            raise ValueError("Cannot deactivate the default workflow")

        default_workflow = TaskWorkflow.objects.filter(team=self.team, is_default=True, is_active=True).first()

        with transaction.atomic():
            if default_workflow:
                self.migrate_tasks_to_workflow(default_workflow)
            else:
                self.unassign_tasks()

            self.is_active = False
            self.save(update_fields=["is_active"])

    @classmethod
    def from_template(cls, template: WorkflowTemplate, team: Team, *, is_default=True):
        with transaction.atomic():
            workflow = cls.objects.create(
                team=team,
                name=template.name,
                description=template.description,
                is_default=is_default,
                is_active=True,
            )

            stages = [
                WorkflowStage(
                    key=stage.key,
                    name=stage.name,
                    position=idx,
                    color=stage.color,
                    is_manual_only=stage.is_manual_only,
                    workflow=workflow,
                )
                for idx, stage in enumerate(template.stages)
            ]

            WorkflowStage.objects.bulk_create(stages)

        return workflow

    @classmethod
    def create_default_workflow(cls, team: Team):
        return TaskWorkflow.from_template(DEFAULT_WORKFLOW_TEMPLATE, team, is_default=True)

    def can_delete(self):
        """Check if this workflow can be safely deleted"""
        if self.is_default:
            return False, "Cannot delete the default workflow"

        return True, ""


class WorkflowStage(models.Model):
    """Individual stages within a workflow."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(TaskWorkflow, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=100, help_text="Stage name (e.g., 'Backlog', 'In Progress')")
    key = models.CharField(max_length=50, help_text="Unique key for this stage within the workflow")
    position = models.IntegerField(help_text="Order of this stage in the workflow")
    color = models.CharField(max_length=7, default="#6b7280", help_text="Hex color for UI display")

    agent_name = models.CharField(
        max_length=50, null=True, blank=True, help_text="ID of the agent responsible for this stage"
    )

    is_manual_only = models.BooleanField(
        default=True, help_text="Whether only manual transitions are allowed from this stage"
    )

    is_archived = models.BooleanField(
        default=False, help_text="Whether this stage is archived (hidden from UI but keeps tasks)"
    )

    fallback_stage = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Stage to move tasks to if this stage is deleted",
    )  # NOTE: We probably don't need this? We can just move it to the previous stage, we're rarely going to bother setting this

    class Meta:
        db_table = "posthog_workflow_stage"
        unique_together = [("workflow", "key"), ("workflow", "position")]
        ordering = ["position"]

    def __str__(self):
        return f"{self.workflow.name}: {self.name}"

    def delete(self, *args, **kwargs):
        """Override delete to handle task runs in this stage."""

        with transaction.atomic():
            # Move task runs to fallback stage or first available stage
            target_stage = self.fallback_stage or self.workflow.stages.exclude(id=self.id).first()

            if target_stage:
                TaskRun.objects.filter(current_stage=self).update(current_stage=target_stage)
            else:
                # No other stages available, clear stage from task runs
                TaskRun.objects.filter(current_stage=self).update(current_stage=None)

            super().delete(*args, **kwargs)

    @property
    def next_stage(self):
        return self.workflow.stages.filter(position__gt=self.position, is_archived=False).order_by("position").first()

    def archive(self):
        self.is_archived = True
        self.save(update_fields=["is_archived"])

    @property
    def agent_definition(self):
        if hasattr(self, "agent_name") and self.agent_name:
            return get_agent_by_id(self.agent_name)
        return None


class Task(models.Model):
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
    position = models.IntegerField(default=0)

    # Workflow configuration
    workflow = models.ForeignKey(
        TaskWorkflow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        help_text="Custom workflow for this task (if not using default)",
    )

    # Repository configuration
    github_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"kind": "github"},
        help_text="GitHub integration for this task",
    )

    repository_config = models.JSONField(
        default=dict, help_text="Repository configuration with organization and repository fields"
    )

    # DEPRECATED FIELDS - these have been moved to TaskRun
    # These fields are kept for backwards compatibility but should not be used
    # editable=False prevents them from appearing in forms/admin
    current_stage = models.ForeignKey(
        WorkflowStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        help_text="DEPRECATED: Moved to TaskRun.current_stage. Use task.latest_run.current_stage instead.",
    )
    github_branch = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        editable=False,
        help_text="DEPRECATED: Moved to TaskRun.branch. Use task.latest_run.branch instead.",
    )
    github_pr_url = models.URLField(
        blank=True,
        null=True,
        editable=False,
        help_text="DEPRECATED: Moved to TaskRun.output['pr_url']. Use task.latest_run.output.get('pr_url') instead.",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task"
        managed = True
        ordering = ["position"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.task_number is None:
            self._assign_task_number()

        # Auto-assign default workflow if no workflow is set
        if not self.workflow:
            default_workflow = TaskWorkflow.objects.filter(team=self.team, is_default=True, is_active=True).first()
            if default_workflow:
                self.workflow = default_workflow

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

    # TODO: Support only one repository, 1 Task = 1 PR probably makes the most sense for scoping
    @property
    def repository_list(self) -> list[dict]:
        """
        Returns list of repositories this task can work with
        Format: [{"org": "PostHog", "repo": "repo-name", "integration_id": 123, "full_name": "PostHog/repo-name"}]
        """
        config = self.repository_config
        if config.get("organization") and config.get("repository"):
            full_name = f"{config.get('organization')}/{config.get('repository')}".lower()
            return [
                {
                    "org": config.get("organization"),
                    "repo": config.get("repository"),
                    "integration_id": self.github_integration_id,
                    "full_name": full_name,
                }
            ]
        return []

    def can_access_repository(self, org: str, repo: str) -> bool:
        """Check if task can work with a specific repository"""
        repo_list = self.repository_list
        return any(r["org"] == org and r["repo"] == repo for r in repo_list)

    @property
    def primary_repository(self) -> dict | None:
        """Get the primary repository for this task"""
        repositories = self.repository_list
        if not repositories:
            return None

        # Since we only support single repository, return the first (and only) one
        return repositories[0]

    @property
    def legacy_github_integration(self):
        """Get the team's main GitHub integration if available (legacy compatibility)"""
        if self.github_integration:
            return self.github_integration

        try:
            return Integration.objects.filter(team_id=self.team_id, kind="github").first()
        except Exception:
            return None

    @property
    def effective_workflow(self) -> Optional["TaskWorkflow"]:
        """Get the workflow this task should use (custom or team default)"""
        if self.workflow:
            return self.workflow

        # Fall back to team's default workflow
        try:
            return TaskWorkflow.objects.filter(team=self.team, is_default=True, is_active=True).first()
        except TaskWorkflow.DoesNotExist:
            return None

    @property
    def latest_run(self) -> Optional["TaskRun"]:
        return self.runs.order_by("-created_at").first()

    def _assign_task_number(self) -> None:
        max_task_number = Task.objects.filter(team=self.team).aggregate(models.Max("task_number"))["task_number__max"]
        self.task_number = (max_task_number if max_task_number is not None else -1) + 1

    @staticmethod
    def create_and_run(
        *,
        team: Team,
        title: str,
        description: str,
        origin_product: "Task.OriginProduct",
        user_id: int,  # Will be used to validate the feature flag and create a personal api key for interacting with PostHog.
        repository: str,  # Format: "organization/repository", e.g. "posthog/posthog-js"
    ) -> "Task":
        from products.tasks.backend.temporal.client import execute_task_processing_workflow

        created_by = User.objects.get(id=user_id)

        if not created_by:
            raise ValueError(f"User {user_id} does not exist")

        github_integration = Integration.objects.filter(team=team, kind="github").first()

        if not github_integration:
            raise ValueError(f"Team {team.id} does not have a GitHub integration")

        repository_config = {}

        if "/" in repository:
            org, repo = repository.split("/", 1)
            repository_config = {"organization": org, "repository": repo}
        else:
            raise ValueError(f"Repository must be in format 'organization/repository', got: {repository}")

        task = Task.objects.create(
            team=team,
            title=title,
            description=description,
            origin_product=origin_product,
            created_by=created_by,
            github_integration=github_integration,
            repository_config=repository_config,
        )

        if not task.effective_workflow:
            raise ValueError(f"Task has no workflow configured. Team {team.id} needs a default workflow.")

        execute_task_processing_workflow(
            task_id=str(task.id),
            team_id=task.team.id,
            user_id=user_id,
        )

        return task


class TaskProgress(models.Model):
    """
    DEPRECATED: This model has been renamed to TaskRun.
    Use TaskRun instead. This class is kept for backwards compatibility only.

    The table still exists in the database but should not be used.
    Any attempt to use this model will raise an error.
    """

    class Status(models.TextChoices):
        STARTED = "started", "Started"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="progress_logs")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # Progress tracking
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED)
    current_step = models.CharField(max_length=255, blank=True, help_text="Current step being executed")
    total_steps = models.IntegerField(default=0, help_text="Total number of steps if known")
    completed_steps = models.IntegerField(default=0, help_text="Number of completed steps")

    # Claude Code output
    output_log = models.TextField(blank=True, help_text="Live output from Claude Code execution")
    error_message = models.TextField(blank=True, help_text="Error message if execution failed")

    # Workflow metadata
    workflow_id = models.CharField(max_length=255, blank=True, help_text="Temporal workflow ID")
    workflow_run_id = models.CharField(max_length=255, blank=True, help_text="Temporal workflow run ID")
    activity_id = models.CharField(max_length=255, blank=True, help_text="Temporal activity ID")

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_task_progress"
        ordering = ["-created_at"]

    def __str__(self):
        raise DeprecationWarning(
            "TaskProgress has been renamed to TaskRun. Use TaskRun instead. "
            "This model is deprecated and should not be used."
        )

    def save(self, *args, **kwargs):
        raise DeprecationWarning(
            "TaskProgress has been renamed to TaskRun. Use TaskRun.objects.create() instead. "
            "This model is deprecated and should not be used."
        )

    def delete(self, *args, **kwargs):
        raise DeprecationWarning(
            "TaskProgress has been renamed to TaskRun. Use TaskRun instead. "
            "This model is deprecated and should not be used."
        )

    @classmethod
    def _raise_deprecation_error(cls):
        raise DeprecationWarning(
            "TaskProgress has been renamed to TaskRun. Use TaskRun instead. "
            "This model is deprecated and should not be used."
        )


class TaskRun(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", "Started"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="runs")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    branch = models.CharField(max_length=255, blank=True, null=True, help_text="Branch name for the run")

    current_stage = models.ForeignKey(
        WorkflowStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Current stage in the workflow for this run",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTED)

    # Claude Code output
    log = models.JSONField(blank=True, default=list, help_text="Live output from Claude Code execution")
    error_message = models.TextField(blank=True, null=True, help_text="Error message if execution failed")

    # This is a structured output of the run. This is used to store the PR URL, commit SHA, etc.
    output = models.JSONField(
        blank=True,
        null=True,
        help_text="Run output data (e.g., PR URL, commit SHA, etc.)",
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

    def append_log(self, entries: list[dict]):
        """Append log entries to the log array and save."""
        if not self.log:
            self.log = []
        self.log.extend(entries)
        self.save(update_fields=["log"])

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

    def get_next_stage(self):
        """Get the next stage in the workflow for this run"""
        workflow = self.task.effective_workflow

        if not workflow:
            return None

        if not self.current_stage:
            return workflow.stages.filter(is_archived=False).order_by("position").first()

        return self.current_stage.next_stage


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
            from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

            if os.environ.get("RUNLOOP_API_KEY") and not settings.TEST:
                try:
                    async_to_sync(SandboxEnvironment.delete_snapshot)(self.external_id)
                except Exception as e:
                    raise Exception(
                        f"Failed to delete external snapshot {self.external_id}: {str(e)}. "
                        f"The database record has not been deleted."
                    ) from e

        super().delete(*args, **kwargs)
