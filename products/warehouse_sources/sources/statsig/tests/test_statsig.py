from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statsig import (
    StatsigSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.source import StatsigSource
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.statsig import StatsigResumeConfig


def _driver() -> SourceDriver:
    return SourceDriver(StatsigSource(), StatsigSourceConfig(api_key="console-test-key"))


def _page(rows: list[dict[str, Any]], next_page: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "pagination": {"nextPage": next_page}})


@pytest.mark.parametrize(
    ("schema", "path", "key", "next_page"),
    [
        ("gates", "/console/v1/gates", "id", "/console/v1/gates?page=2&limit=100"),
        (
            "metrics",
            "/console/v1/metrics/list",
            "id",
            "https://statsigapi.net/console/v1/metrics/list?page=2&limit=100",
        ),
        ("audit_logs", "/console/v1/audit_logs", "id", "statsigapi.net/console/v1/audit_logs?page=2&limit=100"),
        ("users", "/console/v1/users", "userID", "/console/v1/users?page=2&limit=100"),
    ],
)
def test_endpoint_walks_to_terminal_page_and_commits_progress(schema: str, path: str, key: str, next_page: str) -> None:
    rows = [{key: "first", "metadata": {"optional": None}}, {key: "last", "metadata": {"tags": []}}]
    result = _driver().run(schema, [_page(rows[:1], next_page), _page(rows[1:])])

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [path, path]
    assert result.params("page") == ["1", "2"]
    assert result.params("limit") == ["100", "100"]
    for request in result.requests:
        assert request.headers["statsig-api-key"] == "console-test-key"
        assert request.headers["statsig-api-version"] == "20240601"
    expected = StatsigResumeConfig(next_url=f"https://statsigapi.net{path}?page=2&limit=100")
    assert result.saved_states == [expected]
    assert result.committed_states == [expected]


def test_empty_page_with_next_link_keeps_progress() -> None:
    result = _driver().run(
        "gates",
        [
            _page([], "/console/v1/gates?page=2&limit=100"),
            _page([{"id": "last"}]),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "last"}]
    assert result.params("page") == ["1", "2"]
    assert result.committed_states == [
        StatsigResumeConfig(next_url="https://statsigapi.net/console/v1/gates?page=2&limit=100")
    ]


def test_resume_starts_after_written_page() -> None:
    result = _driver().run(
        "gates",
        [_page([{"id": "remaining"}])],
        resume_state=StatsigResumeConfig(next_url="https://statsigapi.net/console/v1/gates?page=3&limit=100"),
    )

    assert result.raised is None
    assert result.params("page") == ["3"]
    assert result.rows == [{"id": "remaining"}]


@pytest.mark.parametrize("status", [401, 403])
def test_page_failure_keeps_last_written_checkpoint(status: int) -> None:
    result = _driver().run(
        "gates",
        [
            _page([{"id": "written"}], "/console/v1/gates?page=2&limit=100"),
            ScriptedResponse(status=status, json={"message": "Access denied"}),
        ],
    )

    assert isinstance(result.raised, HTTPError)
    assert result.raised.response is not None
    assert result.raised.response.status_code == status
    assert result.rows == [{"id": "written"}]
    assert result.committed_states == [
        StatsigResumeConfig(next_url="https://statsigapi.net/console/v1/gates?page=2&limit=100")
    ]


@pytest.mark.parametrize("watermark", [None, 1700000000000])
def test_full_refresh_does_not_filter_out_existing_experiments(watermark: int | None) -> None:
    result = _driver().run(
        "experiments",
        [_page([{"id": "older", "createdTime": 1600000000000, "lastModifiedTime": 1800000000000}])],
        should_use_incremental_field=watermark is not None,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.rows[0]["id"] == "older"
    assert result.queries == [{"page": ("1",), "limit": ("100",)}]
