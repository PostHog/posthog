import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


def _no_resume() -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = False
    return manager


@pytest.mark.parametrize("endpoint", ["workflow_runs", "workflow_jobs", "reviews"])
def test_webhook_only_poll_yields_no_rows_when_webhook_inactive(endpoint: str) -> None:
    webhook_source_manager = mock.Mock()
    webhook_source_manager.webhook_enabled = mock.AsyncMock(return_value=False)

    with mock.patch.object(github, "_fetch_page") as fetch_page:
        response = github.github_source(
            personal_access_token="tok",
            repository="acme/widgets",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_no_resume(),
            webhook_source_manager=webhook_source_manager,
        )
        rows = list(response.items())

    assert rows == []
    fetch_page.assert_not_called()
    webhook_source_manager.get_items.assert_not_called()
