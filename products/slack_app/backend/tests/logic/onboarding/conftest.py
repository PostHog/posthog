from collections.abc import Iterator

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def slack_workspace_admin() -> Iterator[MagicMock]:
    with patch(
        "products.slack_app.backend.logic.onboarding.step.is_slack_workspace_admin", return_value=False
    ) as admin:
        yield admin
