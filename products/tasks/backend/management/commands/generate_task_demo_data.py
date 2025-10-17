from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_datetime

from posthog.models.team.team import Team

from products.tasks.backend.models import Task, TaskRun, TaskWorkflow, WorkflowStage


class Command(BaseCommand):
    help = "Generate demo data for the task tracker"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to generate tasks for",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing tasks before generating new ones",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        clear_existing = options["clear"]

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Team with ID {team_id} does not exist!"))
            return

        with transaction.atomic():
            if clear_existing:
                deleted_count = Task.objects.filter(team=team).delete()[0]
                self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} existing tasks"))

            workflow = self._create_or_get_demo_workflow(team)
            self.stdout.write(self.style.SUCCESS(f"Using workflow: {workflow.name}"))

            stages = list(workflow.stages.filter(is_archived=False).order_by("position"))
            stage_map = {stage.key: stage for stage in stages}

            demo_tasks = [
                {
                    "title": "Memory leak in session recording module",
                    "description": "Users reporting browser crashes during long recording sessions, memory usage keeps growing",
                    "origin_product": Task.OriginProduct.ERROR_TRACKING,
                    "position": 1,
                    "created_at": parse_datetime("2024-01-15T10:30:00Z"),
                    "updated_at": parse_datetime("2024-01-15T10:30:00Z"),
                    "stage_key": "in_progress",
                    "run_status": TaskRun.Status.IN_PROGRESS,
                    "branch": "fix/session-recording-memory-leak",
                    "log": "Analyzing memory profile...\nIdentified event listener accumulation\nImplementing cleanup logic",
                },
                {
                    "title": "Add dark mode toggle to settings",
                    "description": "User requested feature to enable dark mode across the entire application interface",
                    "origin_product": Task.OriginProduct.USER_CREATED,
                    "position": 2,
                    "created_at": parse_datetime("2024-01-14T09:15:00Z"),
                    "updated_at": parse_datetime("2024-01-14T09:15:00Z"),
                    "stage_key": "testing",
                    "run_status": TaskRun.Status.IN_PROGRESS,
                    "branch": "feature/dark-mode-toggle",
                    "log": "Created theme context\nImplemented toggle component\nRunning visual regression tests",
                    "output": {"pr_url": "https://github.com/posthog/posthog/pull/12345"},
                },
                {
                    "title": "Add a new form to the homepage to collect user details",
                    "description": "Add a new form to the homepage to collect user details. Email, name, and a checkbox to opt in to marketing emails, the data can just alert, no need to store it.. Make sure it is behind a feature flag.",
                    "origin_product": Task.OriginProduct.EVAL_CLUSTERS,
                    "position": 0,
                    "created_at": parse_datetime("2024-01-13T14:20:00Z"),
                    "updated_at": parse_datetime("2024-01-16T11:45:00Z"),
                    "stage_key": "done",
                    "run_status": TaskRun.Status.COMPLETED,
                    "branch": "feature/homepage-form",
                    "log": "Created form component\nAdded feature flag\nMerged to main",
                    "output": {
                        "pr_url": "https://github.com/posthog/posthog/pull/12340",
                        "commit_sha": "abc123def456",
                    },
                },
                {
                    "title": "User cannot access dashboard after password reset",
                    "description": "Multiple support tickets about users being locked out after password reset flow",
                    "origin_product": Task.OriginProduct.SUPPORT_QUEUE,
                    "position": 0,
                    "created_at": parse_datetime("2024-01-12T16:00:00Z"),
                    "updated_at": parse_datetime("2024-01-17T08:30:00Z"),
                    "stage_key": "todo",
                    "run_status": TaskRun.Status.STARTED,
                    "log": "Investigating password reset flow",
                },
                {
                    "title": "Fix JavaScript error in event tracking",
                    "description": "TypeError: Cannot read property of undefined in tracking script causing events to fail",
                    "origin_product": Task.OriginProduct.ERROR_TRACKING,
                    "position": 0,
                    "created_at": parse_datetime("2024-01-10T11:00:00Z"),
                    "updated_at": parse_datetime("2024-01-19T12:00:00Z"),
                    "stage_key": "done",
                    "run_status": TaskRun.Status.COMPLETED,
                    "branch": "fix/event-tracking-undefined",
                    "log": "Added null check\nAdded tests\nDeployed fix",
                    "output": {
                        "pr_url": "https://github.com/posthog/posthog/pull/12338",
                        "commit_sha": "def456ghi789",
                    },
                },
                {
                    "title": "Custom dashboard widget for conversion metrics",
                    "description": "User-requested feature to create custom widgets showing conversion funnel data",
                    "origin_product": Task.OriginProduct.USER_CREATED,
                    "position": 3,
                    "created_at": parse_datetime("2024-01-09T10:15:00Z"),
                    "updated_at": parse_datetime("2024-01-09T10:15:00Z"),
                    "stage_key": "backlog",
                    "run_status": None,
                },
                {
                    "title": "Background color of the dashboard is not correct",
                    "description": "The background color of the dashboard is not correct, it should be red",
                    "origin_product": Task.OriginProduct.USER_CREATED,
                    "position": 4,
                    "created_at": parse_datetime("2024-01-08T15:30:00Z"),
                    "updated_at": parse_datetime("2024-01-08T15:30:00Z"),
                    "stage_key": "backlog",
                    "run_status": None,
                },
            ]

            created_count = 0
            for task_data in demo_tasks:
                stage_key = task_data.pop("stage_key")
                run_status = task_data.pop("run_status", None)
                branch = task_data.pop("branch", None)
                log = task_data.pop("log", "")
                output = task_data.pop("output", None)

                task = Task.objects.create(team=team, workflow=workflow, **task_data)
                created_count += 1

                if run_status is not None:
                    stage = stage_map.get(stage_key)
                    TaskRun.objects.create(
                        task=task,
                        team=team,
                        current_stage=stage,
                        status=run_status,
                        branch=branch,
                        log=log,
                        output=output,
                        created_at=task_data["created_at"],
                    )

            self.stdout.write(
                self.style.SUCCESS(f"Successfully created {created_count} demo tasks with runs for team '{team.name}'")
            )

            for task in Task.objects.filter(team=team, workflow=workflow).prefetch_related("runs"):
                latest_run = task.latest_run
                if latest_run and latest_run.current_stage:
                    status = f"{latest_run.current_stage.name} ({latest_run.get_status_display()})"
                else:
                    status = "No runs"
                self.stdout.write(f"  - {task.title} ({status})")

    def _create_or_get_demo_workflow(self, team: Team) -> TaskWorkflow:
        workflow = TaskWorkflow.objects.filter(team=team, name="Demo Workflow").first()

        if workflow:
            return workflow

        workflow = TaskWorkflow.objects.create(
            team=team,
            name="Demo Workflow",
            description="Demo workflow for testing task management features",
            color="#3b82f6",
            is_default=False,
            is_active=True,
        )

        stages_data = [
            {"key": "backlog", "name": "Backlog", "color": "#6b7280", "position": 0},
            {"key": "todo", "name": "Todo", "color": "#3b82f6", "position": 1},
            {"key": "in_progress", "name": "In Progress", "color": "#f59e0b", "position": 2},
            {"key": "testing", "name": "Testing", "color": "#8b5cf6", "position": 3},
            {"key": "done", "name": "Done", "color": "#10b981", "position": 4},
        ]

        for stage_data in stages_data:
            WorkflowStage.objects.create(workflow=workflow, **stage_data)

        return workflow
