import os
import random

import pytest

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.temporal.common.logger import configure_logger

from products.tasks.backend.models import SandboxSnapshot, Task
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate


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
def github_integration(ateam):
    """Create a test GitHub integration."""
    integration = Integration.objects.create(
        team=ateam,
        kind="github",
        sensitive_config={"access_token": "fake_token"},
    )

    yield integration

    integration.delete()


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
async def test_task(ateam, auser, github_integration):
    """Create a test task."""

    task = await sync_to_async(Task.objects.create)(
        team=ateam,
        created_by=auser,
        title="Test Task for Temporal Activities",
        description="This is a test task for testing temporal activities",
        origin_product=Task.OriginProduct.USER_CREATED,
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


def get_or_create_test_snapshots(github_integration):
    """Idempotently create or retrieve real snapshots for test repositories.

    Returns a dict with keys:
    - "single": snapshot with just posthog/posthog-js
    - "multi": snapshot with both posthog/posthog-js and posthog/posthog.com
    """
    if not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"):
        pytest.skip("MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set")

    existing_single = SandboxSnapshot.objects.filter(
        integration=github_integration,
        repos=["posthog/posthog-js"],
        status=SandboxSnapshot.Status.COMPLETE,
    ).first()

    existing_multi = SandboxSnapshot.objects.filter(
        integration=github_integration,
        repos__contains=["posthog/posthog-js", "posthog/posthog.com"],
        status=SandboxSnapshot.Status.COMPLETE,
    ).first()

    if existing_single and existing_multi:
        return {"single": existing_single, "multi": existing_multi}

    snapshots = {}
    sandbox = None

    try:
        config = SandboxConfig(
            name=f"test-snapshot-creator-{random.randint(1, 99999)}",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = Sandbox.create(config)

        if not existing_single:
            clone_result = sandbox.clone_repository("posthog/posthog-js", github_token="")
            if clone_result.exit_code == 0:
                single_snapshot_id = sandbox.create_snapshot()
                single_snapshot = SandboxSnapshot.objects.create(
                    integration=github_integration,
                    repos=["posthog/posthog-js"],
                    external_id=single_snapshot_id,
                    status=SandboxSnapshot.Status.COMPLETE,
                )
                snapshots["single"] = single_snapshot
        else:
            snapshots["single"] = existing_single

        if not existing_multi:
            clone_result = sandbox.clone_repository("posthog/posthog.com", github_token="")
            if clone_result.exit_code == 0:
                multi_snapshot_id = sandbox.create_snapshot()
                multi_snapshot = SandboxSnapshot.objects.create(
                    integration=github_integration,
                    repos=["posthog/posthog-js", "posthog/posthog.com"],
                    external_id=multi_snapshot_id,
                    status=SandboxSnapshot.Status.COMPLETE,
                )
                snapshots["multi"] = multi_snapshot
        else:
            snapshots["multi"] = existing_multi

        return snapshots

    finally:
        if sandbox:
            sandbox.destroy()
