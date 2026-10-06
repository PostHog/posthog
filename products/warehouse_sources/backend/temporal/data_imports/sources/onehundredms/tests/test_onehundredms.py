from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
import time_machine
from unittest.mock import MagicMock

import jwt
from requests import Request
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onehundredms import (
    OneHundredMsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.onehundredms import (
    ManagementTokenAuth,
    OneHundredMsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.source import OneHundredMsSource


@pytest.fixture
def config() -> OneHundredMsSourceConfig:
    return OneHundredMsSourceConfig(
        app_access_key="example-access-key", app_secret="example-secret-for-tests-only-12345"
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def make_inputs(endpoint: str, incremental: bool = False, watermark: datetime | str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=endpoint,
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        job_id="test-job",
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if incremental else None,
        incremental_field_type=None,
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.mark.parametrize(
    "endpoint,path", [("sessions", "sessions"), ("recordings", "recordings"), ("live_streams", "live-streams")]
)
@pytest.mark.parametrize("resume_cursor", [None, "saved-cursor"])
def test_paginated_import_and_resume(
    requests_mock: Mocker,
    config: OneHundredMsSourceConfig,
    manager: MagicMock,
    endpoint: str,
    path: str,
    resume_cursor: str | None,
) -> None:
    if resume_cursor:
        manager.can_resume.return_value = True
        manager.load_state.return_value = OneHundredMsResumeConfig(cursor=resume_cursor)
    requests_mock.get(
        f"https://api.100ms.live/v2/{path}",
        [
            {"json": {"data": [{"id": "row-1", "created_at": "2026-01-01T00:00:00Z"}], "last": "next-cursor"}},
            {"json": {"data": [{"id": "row-2", "created_at": "2025-12-31T00:00:00Z"}], "last": None}},
        ],
    )
    response = OneHundredMsSource().source_for_pipeline(config, manager, make_inputs(endpoint))
    rows = [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]
    assert [row["id"] for row in rows] == ["row-1", "row-2"]
    assert requests_mock.call_count == 2
    queries = [parse_qs(urlsplit(request.url).query) for request in requests_mock.request_history]
    assert queries[0].get("start") == ([resume_cursor] if resume_cursor else None)
    assert queries[1]["start"] == ["next-cursor"]
    assert all(query["limit"] == ["100"] for query in queries)
    if endpoint == "sessions":
        assert all(query["active"] == ["false"] for query in queries)
    token = requests_mock.request_history[0].headers["Authorization"].removeprefix("Bearer ")
    payload = jwt.decode(token, config.app_secret, algorithms=["HS256"])
    assert payload["access_key"] == config.app_access_key
    assert payload["type"] == "management"
    assert payload["version"] == 2
    assert payload["nbf"] == payload["iat"]
    assert payload["exp"] - payload["iat"] == 86400
    assert UUID(payload["jti"]).version == 4
    manager.save_state.assert_called_once_with(OneHundredMsResumeConfig(cursor="next-cursor"))


@pytest.mark.parametrize("terminal", [{"data": []}, {"data": [], "last": ""}, {"data": [], "last": None}])
def test_empty_terminal_page(
    requests_mock: Mocker, config: OneHundredMsSourceConfig, manager: MagicMock, terminal: dict[str, Any]
) -> None:
    requests_mock.get("https://api.100ms.live/v2/recordings", json=terminal)
    response = OneHundredMsSource().source_for_pipeline(config, manager, make_inputs("recordings"))
    assert list(cast(Iterable[Any], response.items())) == []
    assert requests_mock.call_count == 1
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "endpoint,incremental,watermark,expected",
    [
        ("sessions", True, None, None),
        ("sessions", False, "2026-01-01T00:00:00Z", None),
        ("sessions", True, "2026-01-01T00:00:00.123456Z", "2026-01-01T00:00:00.123Z"),
        ("sessions", True, "2026-01-01T02:00:00+02:00", "2026-01-01T00:00:00.000Z"),
        ("sessions", True, datetime(2026, 1, 1), "2026-01-01T00:00:00.000Z"),
        ("sessions", True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00.000Z"),
        ("recordings", True, "2026-01-01T00:00:00Z", None),
        ("live_streams", False, "2026-01-01T00:00:00Z", None),
    ],
)
def test_incremental_filter_is_retained_on_every_page(
    requests_mock: Mocker,
    config: OneHundredMsSourceConfig,
    manager: MagicMock,
    endpoint: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    requests_mock.get(
        f"https://api.100ms.live/v2/{endpoint.replace('_', '-')}",
        [
            {"json": {"data": [{"id": "example-row"}], "last": "next-cursor"}},
            {"json": {"data": [], "last": None}},
        ],
    )
    response = OneHundredMsSource().source_for_pipeline(config, manager, make_inputs(endpoint, incremental, watermark))
    list(cast(Iterable[Any], response.items()))
    assert requests_mock.call_count == 2
    for request in requests_mock.request_history:
        query = parse_qs(urlsplit(request.url).query)
        assert query.get("after") == ([expected] if expected else None)
    if endpoint == "sessions" and incremental:
        assert response.sort_mode == "desc"


@pytest.mark.parametrize("elapsed,refresh", [(60, False), (86339, False), (86340, True), (86401, True)])
def test_token_refresh(config: OneHundredMsSourceConfig, elapsed: int, refresh: bool) -> None:
    auth = ManagementTokenAuth(config.app_access_key, config.app_secret)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with time_machine.travel(start, tick=False) as clock:
        first = Request("GET", "https://api.100ms.live/v2/sessions", auth=auth).prepare()
        clock.move_to(start + timedelta(seconds=elapsed))
        second = Request("GET", "https://api.100ms.live/v2/sessions", auth=auth).prepare()
        assert (first.headers["Authorization"] != second.headers["Authorization"]) is refresh
        token = second.headers["Authorization"].removeprefix("Bearer ")
        payload = jwt.decode(token, config.app_secret, algorithms=["HS256"])
        assert payload["iat"] == int(start.timestamp()) + (elapsed if refresh else 0)
        assert set(auth.secret_values()) == {config.app_access_key, config.app_secret, token}


@pytest.mark.parametrize("body", [{"data": [{"id": "row-1"}], "last": "saved-cursor"}, {"unexpected": []}])
def test_invalid_pagination_fails_instead_of_silently_losing_data(
    requests_mock: Mocker, config: OneHundredMsSourceConfig, manager: MagicMock, body: dict[str, Any]
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = OneHundredMsResumeConfig(cursor="saved-cursor")
    requests_mock.get("https://api.100ms.live/v2/recordings", json=body)
    response = OneHundredMsSource().source_for_pipeline(config, manager, make_inputs("recordings"))
    with pytest.raises(ValueError):
        list(cast(Iterable[Any], response.items()))
    assert requests_mock.call_count == 1
    manager.save_state.assert_not_called()


def test_unknown_table_is_rejected(config: OneHundredMsSourceConfig, manager: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        OneHundredMsSource().source_for_pipeline(config, manager, make_inputs("missing"))
