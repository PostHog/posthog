import os
import random

import pytest

from temporalio.testing import ActivityEnvironment

from posthog.models import Integration, OAuthApplication, Organization, OrganizationMembership, Team, User
from posthog.temporal.common.logger import configure_logger

from products.tasks.backend.models import SandboxSnapshot, Task, TaskRun
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.create_snapshot.activities.get_snapshot_context import SnapshotContext
from products.tasks.backend.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()


@pytest.fixture(autouse=True)
def array_oauth_app():
    """Create the Array OAuth application for tests."""
    app, _ = OAuthApplication.objects.get_or_create(
        client_id=ARRAY_APP_CLIENT_ID_DEV,
        defaults={
            "name": "Array Test App",
            "client_type": OAuthApplication.CLIENT_PUBLIC,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://app.posthog.com/callback",
            "algorithm": "RS256",
        },
    )
    yield app


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
def test_team(team):
    """Alias for team fixture."""
    return team


@pytest.fixture
def user(team):
    user = User.objects.create(
        email=f"test-{random.randint(1, 99999)}@example.com",
        password="testpassword123",
    )

    OrganizationMembership.objects.create(
        user=user,
        organization_id=team.organization_id,
    )

    yield user

    user.delete()


@pytest.fixture
def github_integration(team):
    """Create a test GitHub integration."""
    integration = Integration.objects.create(
        team=team,
        kind="github",
        sensitive_config={"access_token": "fake_token"},
    )

    yield integration

    integration.delete()


@pytest.fixture
def test_task(team, user, github_integration):
    """Create a test task."""

    task = Task.objects.create(
        team=team,
        created_by=user,
        title="Test Task for Temporal Activities",
        description="This is a test task for testing temporal activities",
        origin_product=Task.OriginProduct.USER_CREATED,
        github_integration=github_integration,
        repository="posthog/posthog-js",
    )

    yield task

    task.soft_delete()


@pytest.fixture
def test_task_run(test_task):
    """Create a test task run."""
    task_run = TaskRun.objects.create(
        task=test_task,
        team=test_task.team,
        status=TaskRun.Status.QUEUED,
    )

    yield task_run

    # NOTE: TaskRun does not get deleted


@pytest.fixture
def task_context(test_task, test_task_run) -> TaskProcessingContext:
    """Create a TaskProcessingContext for testing."""
    return TaskProcessingContext(
        task_id=str(test_task.id),
        run_id=str(test_task_run.id),
        team_id=test_task.team_id,
        github_integration_id=test_task.github_integration_id,
        repository=test_task.repository,
        distinct_id=test_task.created_by.distinct_id or "test-distinct-id",
    )


@pytest.fixture
def snapshot_context(github_integration, team) -> SnapshotContext:
    """Create a SnapshotContext for testing."""
    return SnapshotContext(
        github_integration_id=github_integration.id,
        repository="posthog/posthog-js",
        team_id=team.id,
    )


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
