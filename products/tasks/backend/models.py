import uuid
from typing import Optional

from django.db import models
from django.utils import timezone

from django_deprecate_fields import deprecate_field

from products.tasks.backend.agents import get_agent_by_id


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

    def get_active_stages(self):
        """Get all non-archived stages."""
        return self.stages.filter(is_archived=False)

    def get_tasks_in_workflow(self):
        """Get all tasks currently using this workflow."""
        return Task.objects.filter(workflow=self)

    def can_delete(self) -> tuple[bool, str]:
        """Workflows can always be deleted; tasks will be moved to backlog (no workflow)."""
        return True, ""

    def delete(self, *args, **kwargs):
        """Override delete to remove workflow from tasks so they go to backlog."""
        from django.db import transaction

        with transaction.atomic():
            Task.objects.filter(workflow=self).update(workflow=None, current_stage=None)
            super().delete(*args, **kwargs)

    def migrate_tasks_to_workflow(self, target_workflow: "TaskWorkflow"):
        """Migrate all tasks from this workflow to another workflow. Returns number of tasks updated."""
        from django.db import transaction

        # No-op if migrating to self
        if target_workflow.id == self.id:
            return 0

        # Extra safety: ensure both workflows belong to the same team
        if self.team_id != target_workflow.team_id:
            raise ValueError("Source and target workflows must belong to the same team")

        tasks_qs = self.get_tasks_in_workflow().select_related("current_stage")
        if not tasks_qs.exists():
            return 0

        # Prefetch target stages once; preserve deterministic fallback using stage position ordering
        active_stages = list(target_workflow.stages.filter(is_archived=False).order_by("position"))
        stages_by_key = {stage.key: stage for stage in active_stages}
        fallback_stage = active_stages[0] if active_stages else None

        updated_tasks = []
        with transaction.atomic():
            for task in tasks_qs:
                # Match by stage key when possible, otherwise fallback (which can be None)
                next_stage = None
                if task.current_stage and task.current_stage.key in stages_by_key:
                    next_stage = stages_by_key[task.current_stage.key]
                else:
                    next_stage = fallback_stage

                if task.workflow_id != target_workflow.id or task.current_stage != next_stage:
                    task.workflow = target_workflow
                    task.current_stage = next_stage
                    updated_tasks.append(task)

            if updated_tasks:
                Task.objects.bulk_update(updated_tasks, ["workflow", "current_stage"])

        return len(updated_tasks)

    def deactivate_safely(self):
        """Deactivate workflow and move tasks to team default."""
        if self.is_default:
            raise ValueError("Cannot deactivate the default workflow")

        # Find team's default workflow
        default_workflow = (
            TaskWorkflow.objects.filter(team=self.team, is_default=True, is_active=True).exclude(id=self.id).first()
        )

        if default_workflow:
            self.migrate_tasks_to_workflow(default_workflow)
        else:
            # No default workflow, revert tasks to no workflow
            tasks = self.get_tasks_in_workflow()
            for task in tasks:
                task.workflow = None
                task.current_stage = None
                task.save(update_fields=["workflow", "current_stage"])

        self.is_active = False
        self.save(update_fields=["is_active"])

    @classmethod
    def create_default_workflow(cls, team):
        """Create a default workflow that matches the current hardcoded behavior."""
        from django.db import transaction

        with transaction.atomic():
            # Create the workflow
            workflow = cls.objects.create(
                team=team,
                name="Default Code Generation Workflow",
                description="Default workflow for code generation tasks",
                is_default=True,
                is_active=True,
            )

            stages_data = [
                {"key": "backlog", "name": "Backlog", "position": 0, "color": "#6b7280", "is_manual_only": True},
                {"key": "todo", "name": "To Do", "position": 1, "color": "#3b82f6", "is_manual_only": True},
                {
                    "key": "in_progress",
                    "name": "In Progress",
                    "position": 2,
                    "color": "#f59e0b",
                    "is_manual_only": False,
                },
                {"key": "testing", "name": "Testing", "position": 3, "color": "#8b5cf6", "is_manual_only": False},
                {"key": "done", "name": "Done", "position": 4, "color": "#10b981", "is_manual_only": True},
            ]

            stages = {}
            for stage_data in stages_data:
                stage = WorkflowStage.objects.create(workflow=workflow, **stage_data)
                stages[stage.key] = stage

            # Assign agents to appropriate stages using agent names
            stages["in_progress"].agent_name = "code_generation"  # Agent processes this stage
            stages["testing"].agent_name = "code_generation"  # Agent processes this stage
            # Other stages remain manual (no agent_name)

            # Update stages with agent assignments
            for stage in stages.values():
                stage.save()

            return workflow


class WorkflowStage(models.Model):
    """Individual stages within a workflow."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(TaskWorkflow, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=100, help_text="Stage name (e.g., 'Backlog', 'In Progress')")
    key = models.CharField(max_length=50, help_text="Unique key for this stage within the workflow")
    position = models.IntegerField(help_text="Order of this stage in the workflow")
    color = models.CharField(max_length=7, default="#6b7280", help_text="Hex color for UI display")
    agent = deprecate_field(
        models.ForeignKey(
            "AgentDefinition",
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
            help_text="DEPRECATED: Agent responsible for processing tasks in this stage",
        )
    )
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
    )

    class Meta:
        db_table = "posthog_workflow_stage"
        unique_together = [("workflow", "key"), ("workflow", "position")]
        ordering = ["position"]

    def __str__(self):
        return f"{self.workflow.name}: {self.name}"

    def delete(self, *args, **kwargs):
        """Override delete to handle tasks in this stage."""
        from django.db import transaction

        with transaction.atomic():
            # Move tasks to fallback stage or first available stage
            target_stage = self.fallback_stage or self.workflow.stages.exclude(id=self.id).first()

            if target_stage:
                # Move all tasks to the target stage
                Task.objects.filter(current_stage=self).update(current_stage=target_stage)
            else:
                # No other stages available, remove workflow association
                Task.objects.filter(current_stage=self).update(current_stage=None, workflow=None)

            super().delete(*args, **kwargs)

    def archive(self):
        """Archive this stage instead of deleting it."""
        self.is_archived = True
        self.save(update_fields=["is_archived"])

    def get_agent_definition(self):
        """Get the hardcoded agent definition for this stage."""
        if hasattr(self, "agent_name") and self.agent_name:
            return get_agent_by_id(self.agent_name)
        return None


class AgentDefinition(models.Model):
    """DEPRECATED: This model is being removed. Agents are now hardcoded in agents.py"""

    class AgentType(models.TextChoices):
        CODE_GENERATION = "code_generation", "Code Generation Agent"
        TRIAGE = "triage", "Triage Agent"
        REVIEW = "review", "Review Agent"
        TESTING = "testing", "Testing Agent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255, help_text="Human-readable name for this agent")
    agent_type = models.CharField(max_length=50, choices=AgentType.choices)
    description = models.TextField(blank=True, help_text="Description of what this agent does")
    config = models.JSONField(default=dict, help_text="Agent-specific configuration")
    is_active = models.BooleanField(default=True, help_text="Whether this agent is available for use")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_agent_definition"
        unique_together = [("team", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_agent_type_display()})"


class Task(models.Model):
    class OriginProduct(models.TextChoices):
        ERROR_TRACKING = "error_tracking", "Error Tracking"
        EVAL_CLUSTERS = "eval_clusters", "Eval Clusters"
        USER_CREATED = "user_created", "User Created"
        SUPPORT_QUEUE = "support_queue", "Support Queue"
        SESSION_SUMMARIES = "session_summaries", "Session Summaries"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
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
        help_text="Custom workflow for this task (if not using default)",
    )
    current_stage = models.ForeignKey(
        WorkflowStage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Current stage in the workflow (overrides status field when workflow is set)",
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

    github_branch = models.CharField(max_length=255, blank=True, null=True, help_text="Branch created for this task")
    github_pr_url = models.URLField(blank=True, null=True, help_text="Pull request URL when created")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task"
        managed = True
        ordering = ["position"]

    def __str__(self):
        if self.current_stage:
            return f"{self.title} ({self.current_stage.key})"
        return f"{self.title} (no workflow)"

    def save(self, *args, **kwargs):
        """Override save to handle workflow consistency."""
        if self.workflow and not self.current_stage:
            first_stage = self.workflow.get_active_stages().first()
            if first_stage:
                self.current_stage = first_stage

        if self.current_stage and self.workflow and self.current_stage.workflow != self.workflow:
            self.current_stage = None

        super().save(*args, **kwargs)

    @property
    def repository_list(self) -> list[dict]:
        """
        Returns list of repositories this task can work with
        Format: [{"org": "PostHog", "repo": "repo-name", "integration_id": 123, "full_name": "PostHog/repo-name"}]
        """
        config = self.repository_config
        if config.get("organization") and config.get("repository"):
            return [
                {
                    "org": config.get("organization"),
                    "repo": config.get("repository"),
                    "integration_id": self.github_integration_id,
                    "full_name": f"{config.get('organization')}/{config.get('repository')}",
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

        # Fallback to team's first GitHub integration
        from posthog.models.integration import Integration

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

    def get_next_stage(self):
        """Get the next stage in the linear workflow"""
        workflow = self.effective_workflow
        if not workflow:
            return None

        current_stage = self.current_stage
        if not current_stage:
            return workflow.stages.filter(is_archived=False).order_by("position").first()

        return (
            workflow.stages.filter(position__gt=current_stage.position, is_archived=False).order_by("position").first()
        )

    def resolve_orphaned_stage(self):
        """Fix this task if its current stage is archived or invalid."""
        if not self.current_stage or self.current_stage.is_archived:
            workflow = self.effective_workflow
            if workflow:
                # Find a suitable stage to move to
                fallback_stage = None

                if self.current_stage and self.current_stage.fallback_stage:
                    fallback_stage = self.current_stage.fallback_stage
                else:
                    fallback_stage = workflow.get_active_stages().first()

                if fallback_stage:
                    self.current_stage = fallback_stage
                    self.save(update_fields=["current_stage"])
                else:
                    self.workflow = None
                    self.current_stage = None
                    self.save(update_fields=["workflow", "current_stage"])


class TaskProgress(models.Model):
    """Tracks real-time progress of Claude Code execution for tasks."""

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
        return f"Progress for {self.task.title} - {self.get_status_display()}"

    def append_output(self, text: str):
        """Append text to the output log and save."""
        if self.output_log:
            self.output_log += "\n" + text
        else:
            self.output_log = text
        self.updated_at = timezone.now()
        self.save(update_fields=["output_log", "updated_at"])

    def update_progress(
        self, step: str | None = None, completed_steps: int | None = None, total_steps: int | None = None
    ):
        """Update progress information."""
        if step:
            self.current_step = step
        if completed_steps is not None:
            self.completed_steps = completed_steps
        if total_steps is not None:
            self.total_steps = total_steps
        self.updated_at = timezone.now()
        self.save(update_fields=["current_step", "completed_steps", "total_steps", "updated_at"])

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

    @property
    def progress_percentage(self):
        """Calculate progress percentage."""
        if self.total_steps and self.total_steps > 0:
            return min(100, (self.completed_steps / self.total_steps) * 100)
        return 0
