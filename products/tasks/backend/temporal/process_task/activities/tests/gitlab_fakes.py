import uuid

from posthog.models.integration import Integration

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

GITLAB_API = "https://gitlab.com/api/v4/projects/7"
MR_URL = "https://gitlab.com/acme/app/-/merge_requests/3"
GITLAB_BOT = {"id": 99, "username": "project_7_bot_abc"}


def gitlab_merge_request(**overrides: object) -> dict:
    return {
        "iid": 3,
        "web_url": MR_URL,
        "state": "opened",
        "draft": True,
        "title": "Draft: Fix the widget",
        "sha": "abc123",
        "source_branch": "posthog/fix-widget",
        "author": GITLAB_BOT,
        "has_conflicts": False,
        "detailed_merge_status": "draft_status",
        "labels": [],
        "head_pipeline": {"id": 55, "sha": "abc123", "status": "failed", "web_url": f"{MR_URL}/pipelines/55"},
        **overrides,
    }


def gitlab_task_context(task_run: TaskRun) -> TaskProcessingContext:
    integration = Integration.objects.create(
        team=task_run.team,
        kind="gitlab",
        integration_id="gitlab-acme-app",
        config={"hostname": "https://gitlab.com", "path_with_namespace": "acme/app", "project_id": 7},
        sensitive_config={"access_token": "glpat-example"},
    )
    return TaskProcessingContext(
        task_id=str(task_run.task_id),
        run_id=str(task_run.id),
        team_id=task_run.team_id,
        team_uuid=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        github_integration_id=None,
        repository_integration_id=integration.id,
        repository="acme/app",
        distinct_id="user-1",
        pr_loop_enabled=True,
        pr_babysit_enabled=True,
    )
