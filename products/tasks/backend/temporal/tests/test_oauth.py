import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.oauth import create_oauth_access_token


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
