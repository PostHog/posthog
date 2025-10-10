import random

import pytest

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.temporal.common.logger import configure_logger

from products.tasks.backend.models import Task, TaskWorkflow, WorkflowStage


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()


@pytest.fixture
def organization():
    """A test organization."""
    name = f"TasksTestOrg-{random.randint(1, 99999)}"
    org = Organization.objects.create(name=name, is_ai_data_processing_approved=True)
    org.save()

    yield org

    org.delete()


@pytest.fixture
def team(organization):
    """A test team."""
    name = f"TasksTestTeam-{random.randint(1, 99999)}"
    team = Team.objects.create(organization=organization, name=name)
    team.save()

    yield team

    team.delete()


@pytest.fixture
async def aorganization():
    """Async test organization."""
    name = f"TasksTestOrg-{random.randint(1, 99999)}"
    org = await sync_to_async(Organization.objects.create)(name=name, is_ai_data_processing_approved=True)

    yield org

    await sync_to_async(org.delete)()


@pytest.fixture
async def ateam(aorganization):
    """Async test team."""
    name = f"TasksTestTeam-{random.randint(1, 99999)}"
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team

    await sync_to_async(team.delete)()


@pytest.fixture
async def task_workflow(ateam):
    """Create a test workflow with stages."""
    workflow = await sync_to_async(TaskWorkflow.objects.create)(
        team=ateam,
        name="Test Workflow",
        description="Test workflow for temporal activities",
        is_default=True,
        is_active=True,
    )

    stages = []
    for i, (name, key, color) in enumerate(
        [
            ("Backlog", "backlog", "#6b7280"),
            ("Ready", "ready", "#3b82f6"),
            ("In Progress", "in_progress", "#10b981"),
            ("Done", "done", "#22c55e"),
        ]
    ):
        stage = await sync_to_async(WorkflowStage.objects.create)(
            workflow=workflow,
            name=name,
            key=key,
            position=i,
            color=color,
            is_manual_only=(i != 2),  # Only "In Progress" is not manual
            agent_name="claude_code_agent" if i == 2 else None,
        )
        stages.append(stage)

    yield workflow, stages

    await sync_to_async(workflow.delete)()


@pytest.fixture
async def github_integration(ateam):
    """Create a test GitHub integration."""
    integration = await sync_to_async(Integration.objects.create)(
        team=ateam,
        kind="github",
        sensitive_config={"access_token": "fake_token"},
    )

    yield integration

    await sync_to_async(integration.delete)()


@pytest.fixture
async def auser(ateam):
    user = await sync_to_async(User.objects.create)(
        email=f"test-{random.randint(1, 99999)}@example.com",
        password="testpassword123",
    )

    await sync_to_async(OrganizationMembership.objects.create)(
        user=user,
        organization_id=ateam.organization_id,
    )

    yield user
    await sync_to_async(user.delete)()


@pytest.fixture
async def test_task(ateam, auser, task_workflow, github_integration):
    """Create a test task."""
    workflow, stages = task_workflow
    backlog_stage = stages[0]

    task = await sync_to_async(Task.objects.create)(
        team=ateam,
        created_by=auser,
        title="Test Task for Temporal Activities",
        description="This is a test task for testing temporal activities",
        origin_product=Task.OriginProduct.USER_CREATED,
        workflow=workflow,
        current_stage=backlog_stage,
        position=0,
        github_integration=github_integration,
        repository_config={"organization": "PostHog", "repository": "posthog-js"},
    )

    yield task

    await sync_to_async(task.delete)()


@pytest.fixture(autouse=True)
def configure_logger_auto() -> None:
    """Configure logger when running in a Temporal activity environment."""
    configure_logger(cache_logger_on_first_use=False)
