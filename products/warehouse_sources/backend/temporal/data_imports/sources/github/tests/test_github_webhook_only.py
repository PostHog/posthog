import asyncio
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta

import pytest
from unittest import mock

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


def _no_resume() -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = False
    return manager


def _webhook_manager(*, enabled: bool, schema_is_webhook: bool | None = None, items: object = None) -> mock.Mock:
    manager = mock.Mock()
    manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
    if schema_is_webhook is not None:
        manager.schema_is_webhook = mock.AsyncMock(return_value=schema_is_webhook)
    if items is not None:
        manager.get_items = mock.Mock(return_value=items)
    return manager


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _collect(tables: AsyncIterator[pa.Table]) -> list[pa.Table]:
    return [table async for table in tables]


@pytest.mark.parametrize(
    "endpoint",
    [
        "workflow_runs",
        "workflow_jobs",
        "reviews",
        "deployments",
        "deployment_statuses",
        "check_runs",
        "commit_statuses",
    ],
)
def test_webhook_only_poll_yields_no_rows_when_webhook_inactive(endpoint: str) -> None:
    webhook_source_manager = _webhook_manager(enabled=False, schema_is_webhook=True)

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


def test_webhook_enabled_deployment_statuses_reconciles_inactive_statuses() -> None:
    # GitHub fires no deployment_status webhook for the inactive state, so the webhook drain must
    # be chased by a bounded fan-out over recent deployments; without it, rollback/auto_inactive
    # statuses are silently never ingested and a superseded deployment keeps looking current.
    now = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)
    watermark = now - timedelta(hours=1)

    webhook_table = pa.table({"id": [99]})

    async def webhook_items() -> AsyncIterator[pa.Table]:
        yield webhook_table

    webhook_source_manager = _webhook_manager(enabled=True, items=webhook_items())

    deployments_page = [
        # Updated since the watermark (a new status landed): its statuses are re-fetched.
        {"id": 1, "created_at": _iso(now - timedelta(days=1)), "updated_at": _iso(now - timedelta(minutes=5))},
        # In the window but not updated since the watermark: holds no unseen statuses, skipped.
        {"id": 2, "created_at": _iso(now - timedelta(days=2)), "updated_at": _iso(now - timedelta(days=2))},
        # Freshly updated but created outside the 30-day reconcile window: skipped.
        {"id": 3, "created_at": _iso(now - timedelta(days=40)), "updated_at": _iso(now - timedelta(minutes=5))},
    ]
    statuses_page = [
        {"id": 11, "state": "success", "created_at": _iso(now - timedelta(minutes=10))},
        {"id": 12, "state": "inactive", "created_at": _iso(now - timedelta(minutes=5))},
    ]

    def fetch_page(url: str, *args: object, **kwargs: object) -> mock.Mock:
        response = mock.Mock()
        response.headers = {}
        if "/deployments/1/statuses" in url:
            response.json.return_value = statuses_page
        elif "/deployments?" in url:
            response.json.return_value = deployments_page
        else:
            raise AssertionError(f"unexpected fetch: {url}")
        return response

    with (
        mock.patch.object(github, "_fetch_page", side_effect=fetch_page) as fetch_mock,
        mock.patch.object(github, "_now_utc", return_value=now),
    ):
        response = github.github_source(
            personal_access_token="tok",
            repository="acme/widgets",
            endpoint="deployment_statuses",
            logger=mock.Mock(),
            resumable_source_manager=_no_resume(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            webhook_source_manager=webhook_source_manager,
        )
        result = response.items()
        assert isinstance(result, AsyncIterator)
        tables = asyncio.run(_collect(result))

    assert tables[0] is webhook_table
    reconciled = pa.concat_tables(tables[1:])
    assert reconciled.column("id").to_pylist() == [11, 12]
    assert reconciled.column("state").to_pylist() == ["success", "inactive"]
    assert reconciled.column("deployment_id").to_pylist() == [1, 1]
    fetched_urls = [call.args[0] for call in fetch_mock.call_args_list]
    assert not any("/deployments/2/statuses" in url for url in fetched_urls)
    assert not any("/deployments/3/statuses" in url for url in fetched_urls)


@pytest.mark.parametrize(
    "watermark_offset,expected_parents",
    [
        # No watermark: the recency skip is inert, so the cap is the only bound, and it keeps the
        # newest parents.
        (None, ["1", "2"]),
        # Watermark set: every parent past the skip is known to hold an unseen child, and the run
        # advances the watermark past it either way, so capping would drop it permanently.
        (timedelta(days=3), ["1", "2", "3", "4"]),
    ],
)
def test_webhook_enabled_deployment_statuses_reconciliation_caps_the_parent_fan_out(
    watermark_offset: timedelta | None, expected_parents: list[str]
) -> None:
    now = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)

    async def webhook_items() -> AsyncIterator[pa.Table]:
        yield pa.table({"id": [99]})

    webhook_source_manager = _webhook_manager(enabled=True, items=webhook_items())

    # Newest first, the order GitHub returns deployments in and the order the cap relies on.
    # All four sit inside the reconcile window and above any watermark below.
    deployments_page = [
        {
            "id": index,
            "created_at": _iso(now - timedelta(hours=index)),
            "updated_at": _iso(now - timedelta(hours=index)),
        }
        for index in range(1, 5)
    ]

    def fetch_page(url: str, *args: object, **kwargs: object) -> mock.Mock:
        response = mock.Mock()
        response.headers = {}
        if "/statuses" in url:
            response.json.return_value = [{"id": 11, "state": "success", "created_at": _iso(now)}]
        elif "/deployments?" in url:
            response.json.return_value = deployments_page
        else:
            raise AssertionError(f"unexpected fetch: {url}")
        return response

    with (
        mock.patch.object(github.GITHUB_ENDPOINTS["deployment_statuses"], "max_fan_out_parents", 2),
        mock.patch.object(github, "_fetch_page", side_effect=fetch_page) as fetch_mock,
        mock.patch.object(github, "_now_utc", return_value=now),
    ):
        response = github.github_source(
            personal_access_token="tok",
            repository="acme/widgets",
            endpoint="deployment_statuses",
            logger=mock.Mock(),
            resumable_source_manager=_no_resume(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=None if watermark_offset is None else now - watermark_offset,
            webhook_source_manager=webhook_source_manager,
        )
        result = response.items()
        assert isinstance(result, AsyncIterator)
        asyncio.run(_collect(result))

    status_fetches = [url for url in fetch_mock.call_args_list if "/statuses" in url.args[0]]
    assert [url.args[0].split("/deployments/")[1].split("/")[0] for url in status_fetches] == expected_parents


def test_poll_mode_workflow_runs_still_polls() -> None:
    # A legacy workflow_runs schema still configured for poll sync (is_webhook False) must keep
    # polling, not get short-circuited to empty — otherwise it silently freezes once workflow_runs
    # becomes webhook-only.
    webhook_source_manager = _webhook_manager(enabled=False, schema_is_webhook=False)

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
