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
        internal=False,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="posthog_ai",
        internal_run=False,
    )


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_default_task_uses_array_oauth_application(mock_create: MagicMock) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
        internal=False,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="array",
        internal_run=False,
    )


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_internal_task_mints_internal_run_token(mock_create: MagicMock) -> None:
    # Task.internal drives the internal-run marker the LLM gateway requires for
    # internal products (background_agents, signals, conversations).
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
        internal=True,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="array",
        internal_run=True,
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
