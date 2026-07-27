from collections.abc import Iterable

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
    webhook_source_manager.schema_is_webhook = mock.AsyncMock(return_value=True)

    with mock.patch.object(github, "_fetch_page") as fetch_page:
        response = github.github_source(
            personal_access_token="tok",
            repository="acme/widgets",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_no_resume(),
            webhook_source_manager=webhook_source_manager,
        )
        result = response.items()
        # The webhook-only fallback must return a sync, empty iterator — not the async webhook stream.
        assert isinstance(result, Iterable)
        rows = list(result)

    assert rows == []
    # An actual webhook-mode schema is webhook_only, so a reset preserves its table.
    assert response.webhook_only is True
    fetch_page.assert_not_called()
    webhook_source_manager.get_items.assert_not_called()


def test_poll_mode_workflow_runs_still_polls() -> None:
    # A legacy workflow_runs schema still configured for poll sync (is_webhook False) must keep
    # polling, not get short-circuited to empty — otherwise it silently freezes once workflow_runs
    # becomes webhook-only.
    webhook_source_manager = mock.Mock()
    webhook_source_manager.webhook_enabled = mock.AsyncMock(return_value=False)
    webhook_source_manager.schema_is_webhook = mock.AsyncMock(return_value=False)

    empty_page = mock.Mock()
    empty_page.json.return_value = {"workflow_runs": []}
    empty_page.headers = {}

    with mock.patch.object(github, "_fetch_page", return_value=empty_page) as fetch_page:
        response = github.github_source(
            personal_access_token="tok",
            repository="acme/widgets",
            endpoint="workflow_runs",
            logger=mock.Mock(),
            resumable_source_manager=_no_resume(),
            webhook_source_manager=webhook_source_manager,
        )
        result = response.items()
        assert isinstance(result, Iterable)  # poll path is a sync iterator
        list(result)

    fetch_page.assert_called()
    # A legacy poll-mode schema is NOT webhook_only, so a reset still wipes and rebuilds.
    assert response.webhook_only is False
    webhook_source_manager.get_items.assert_not_called()
