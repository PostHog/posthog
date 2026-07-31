import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.oauth import create_oauth_access_token, create_oauth_access_token_for_run


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_posthog_ai_task_uses_posthog_ai_oauth_application(mock_create: MagicMock) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.POSTHOG_AI,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="posthog_ai",
    )


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_default_task_uses_array_oauth_application(mock_create: MagicMock) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="array",
    )


def test_oauth_token_can_disable_task_creator_fallback() -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token(task, user=None, allow_task_creator_fallback=False)


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_run_token_fails_closed_for_slack_run_with_unresolvable_actor(mock_create: MagicMock) -> None:
    from posthog.models import Organization, Team
    from posthog.models.user import User

    organization = Organization.objects.create(name="oauth-run-org")
    team = Team.objects.create(organization=organization, name="oauth-run-team")
    creator = User.objects.create(email="oauth-run-creator@example.com")
    task = Task.objects.create(
        team=team,
        title="Investigate thread",
        created_by=creator,
        origin_product=Task.OriginProduct.SLACK,
    )
    state = {"interaction_origin": "slack", "slack_actor_user_id": creator.id + 999_999}

    # A Slack run whose recorded actor can't be validated must never mint the
    # task creator's token.
    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, state)
    mock_create.assert_not_called()

    # Non-Slack runs keep the creator fallback.
    assert create_oauth_access_token_for_run(task, {}) == "token"


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_loop_run_fails_closed_when_owner_is_not_a_current_org_member(mock_create: MagicMock) -> None:
    from posthog.models import Organization, Team
    from posthog.models.organization import OrganizationMembership
    from posthog.models.user import User

    organization = Organization.objects.create(name="loop-cred-org")
    team = Team.objects.create(organization=organization, name="loop-cred-team")
    owner = User.objects.create(email="loop-owner-cred@example.com")
    task = Task.objects.create(team=team, title="Loop run", created_by=owner, origin_product=Task.OriginProduct.LOOP)
    state = {"loop_id": "loop-1"}

    # Re-check at mint time: a just-offboarded owner (no membership) must not mint credentials for an
    # in-flight run, even though the async loop cancellation may not have landed yet.
    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, state)
    mock_create.assert_not_called()

    OrganizationMembership.objects.create(organization=organization, user=owner)
    assert create_oauth_access_token_for_run(task, state) == "token"


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_loop_run_rechecks_owner_active_state_from_the_database(mock_create: MagicMock) -> None:
    from posthog.models import Organization, Team
    from posthog.models.organization import OrganizationMembership
    from posthog.models.user import User

    organization = Organization.objects.create(name="loop-fresh-org")
    team = Team.objects.create(organization=organization, name="loop-fresh-team")
    owner = User.objects.create(email="loop-fresh-owner@example.com")
    OrganizationMembership.objects.create(organization=organization, user=owner)
    task = Task.objects.create(team=team, title="Loop run", created_by=owner, origin_product=Task.OriginProduct.LOOP)
    state = {"loop_id": "loop-1"}

    # Deactivate directly in the DB; `task.created_by` stays cached as active. The mint must re-read
    # the row, not trust the stale in-memory `is_active`.
    User.objects.filter(id=owner.id).update(is_active=False)

    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, state)
    mock_create.assert_not_called()


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_loop_fired_run_excludes_loop_write_scope(mock_create: MagicMock) -> None:
    """A run whose state carries loop_id must never receive a loop:write-scoped token,
    regardless of the requested scopes — this is the token-layer half of the loop CRUD
    MCP block (see LOOP_FIRED_RUN_EXCLUDED_SCOPES)."""
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    create_oauth_access_token(task, scopes=["loop:read", "loop:write", "task:read"], loop_id="loop-1")

    _, kwargs = mock_create.call_args
    assert "loop:write" not in kwargs["scopes"]
    assert "loop:read" in kwargs["scopes"]
    assert "task:read" in kwargs["scopes"]


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_non_loop_run_keeps_loop_write_scope(mock_create: MagicMock) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    create_oauth_access_token(task, scopes=["loop:read", "loop:write", "task:read"], loop_id=None)

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes=["loop:read", "loop:write", "task:read"],
        application="array",
    )
