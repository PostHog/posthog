from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.source import SpeedcurveSource
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.speedcurve import (
    SpeedcurveResumeConfig,
    speedcurve_source,
    validate_credentials,
)

NOW = datetime(2026, 6, 15, tzinfo=UTC)
BASE_URL = "https://api.speedcurve.com/v1/"


@pytest.fixture(autouse=True)
def fixed_clock() -> Iterator[None]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.speedcurve.datetime"
    ) as clock:
        clock.now.return_value = NOW
        yield


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def _source(
    manager: MagicMock,
    endpoint: str,
    incremental: bool = False,
    watermark: int | float | str | None = None,
) -> SourceResponse:
    return speedcurve_source(
        api_key="fake-key",
        api_version="v1",
        endpoint=endpoint,
        team_id=1,
        job_id="speedcurve-test",
        resumable_source_manager=manager,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )


def _rows(source: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast(Iterable[list[dict[str, Any]]], source.items()) for row in page]


@responses.activate
@pytest.mark.parametrize(
    ("endpoint", "body", "expected"),
    [
        ("sites", {"sites": [{"site_id": 1, "name": "Example"}]}, [{"site_id": 1, "name": "Example"}]),
        ("notes", {"notes": [{"note_id": 2, "note": "New layout"}]}, [{"note_id": 2, "note": "New layout"}]),
        ("budgets", {"budgets": [{"budget_id": 3, "status": "over"}]}, [{"budget_id": 3, "status": "over"}]),
        (
            "urls",
            {
                "sites": [
                    {"site_id": 1, "urls": [{"url_id": 4, "url": "https://example.com"}]},
                    {"site_id": 2, "urls": [{"url_id": 4, "url": "https://example.org"}]},
                    {"site_id": 3, "urls": []},
                ]
            },
            [
                {"site_id": 1, "url_id": 4, "url": "https://example.com"},
                {"site_id": 2, "url_id": 4, "url": "https://example.org"},
            ],
        ),
    ],
)
def test_single_page_rows_and_auth(
    manager: MagicMock, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]
) -> None:
    responses.get(BASE_URL + endpoint, json=body)

    source = _source(manager, endpoint)
    assert _rows(source) == expected
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Basic ZmFrZS1rZXk6eA=="
    assert not urlsplit(request.url).query
    if endpoint == "urls":
        assert len({tuple(row[key] for key in source.primary_keys or []) for row in expected}) == 2
    manager.can_resume.assert_not_called()


@responses.activate
@pytest.mark.parametrize("endpoint", ["tests", "deploys"])
def test_pagination_and_resume_checkpoint(manager: MagicMock, endpoint: str) -> None:
    selector = "data" if endpoint == "tests" else "deploys"
    key = "test_id" if endpoint == "tests" else "deploy_id"
    for page in (1, 2):
        body: dict[str, Any] = {selector: [{key: page, "timestamp": int(NOW.timestamp()) - page}]}
        if endpoint == "tests":
            body["meta"] = {"last_page": 2}
        responses.get(BASE_URL + endpoint, json=body)
    if endpoint == "deploys":
        responses.get(BASE_URL + endpoint, json={selector: []})

    source = _source(manager, endpoint)
    assert [row[key] for row in _rows(source)] == [1, 2]
    query_params = [parse_qs(urlsplit(call.request.url).query) for call in responses.calls]
    assert [params["page"] for params in query_params] == (
        [["1"], ["2"]] if endpoint == "tests" else [["1"], ["2"], ["3"]]
    )
    assert all(params["per_page"] == ["100"] for params in query_params)
    assert all(params["end_timestamp"] == [str(int(NOW.timestamp()))] for params in query_params)
    checkpoints = [call.args[0] for call in manager.save_state.call_args_list]
    assert [checkpoint.page for checkpoint in checkpoints] == ([2] if endpoint == "tests" else [2, 3])
    assert all(checkpoint.end_timestamp == int(NOW.timestamp()) for checkpoint in checkpoints)
    assert source.sort_mode == "desc"
    manager.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    manager.clear_state.assert_called_once()


@responses.activate
@pytest.mark.parametrize("endpoint", ["tests", "deploys"])
def test_resume_preserves_range_when_clock_and_watermark_change(manager: MagicMock, endpoint: str) -> None:
    saved = SpeedcurveResumeConfig(page=4, start_timestamp=1751000000, end_timestamp=1752000000)
    manager.can_resume.return_value = True
    manager.load_state.return_value = saved
    selector = "data" if endpoint == "tests" else "deploys"
    responses.get(BASE_URL + endpoint, json={selector: []})

    assert _rows(_source(manager, endpoint, incremental=True, watermark=1780000000)) == []
    assert parse_qs(urlsplit(responses.calls[0].request.url).query) == {
        "page": ["4"],
        "per_page": ["100"],
        "start_timestamp": ["1751000000"],
        "end_timestamp": ["1752000000"],
    }
    manager.save_state.assert_not_called()


@responses.activate
@pytest.mark.parametrize("endpoint", ["tests", "deploys"])
@pytest.mark.parametrize(
    ("incremental", "watermark"),
    [(False, 1780000000), (True, None), (True, 1780000000), (True, "1780000000"), (True, 1)],
)
def test_incremental_and_full_refresh_ranges(
    manager: MagicMock, endpoint: str, incremental: bool, watermark: int | str | None
) -> None:
    selector = "data" if endpoint == "tests" else "deploys"
    responses.get(BASE_URL + endpoint, json={selector: []})

    assert _rows(_source(manager, endpoint, incremental, watermark)) == []
    params = parse_qs(urlsplit(responses.calls[0].request.url).query)
    expected_start = int(watermark) if incremental and watermark is not None else None
    if endpoint == "tests":
        retention_start = int((NOW - timedelta(days=364)).timestamp())
        expected_start = max(expected_start or retention_start, retention_start)
    if expected_start is None:
        assert "start_timestamp" not in params
    else:
        assert params["start_timestamp"] == [str(expected_start)]
    assert len(responses.calls) == 1
    manager.save_state.assert_not_called()


@responses.activate
def test_validation_uses_one_cheap_request() -> None:
    responses.get(BASE_URL + "sites", json={"sites": []})
    assert validate_credentials("fake-key", "v1") == (True, None)
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert parse_qs(urlsplit(request.url).query) == {"median": ["0"]}
    assert request.headers["Authorization"] == "Basic ZmFrZS1rZXk6eA=="


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_terminal_and_have_actionable_messages(manager: MagicMock, status: int) -> None:
    responses.get(
        BASE_URL + "sites",
        status=status,
        json={
            "status": "error",
            "message": "A valid API key is required. Check you have the correct API key for your team and your account is active.",
        },
    )
    valid, message = validate_credentials("fake-key", "v1")
    assert valid is False
    assert message is not None and "Check" in message and "API key" in message
    assert len(responses.calls) == 1
    with pytest.raises(HTTPError) as error:
        _rows(_source(manager, "sites"))
    mapped = [
        value for pattern, value in SpeedcurveSource().get_non_retryable_errors().items() if pattern in str(error.value)
    ]
    assert mapped == [message]
    assert len(responses.calls) == 2


@responses.activate
@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry_without_becoming_invalid_credentials(status: int) -> None:
    responses.get(BASE_URL + "sites", status=status, json={"message": "Unavailable"}, headers={"Retry-After": "0"})
    with pytest.raises(RESTClientRetryableError):
        validate_credentials("fake-key", "v1")
    assert len(responses.calls) == 5


@responses.activate
def test_other_client_errors_propagate() -> None:
    responses.get(BASE_URL + "sites", status=422, json={"message": "Parameters are not valid."})
    with pytest.raises(HTTPError):
        validate_credentials("fake-key", "v1")
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("endpoint", ["sites", "urls", "tests", "deploys", "notes", "budgets"])
def test_missing_collection_does_not_silently_empty_table(manager: MagicMock, endpoint: str) -> None:
    responses.get(BASE_URL + endpoint, json={"unexpected": []})
    with pytest.raises(ValueError, match="selector"):
        _rows(_source(manager, endpoint))


def test_unknown_table_fails_before_network(manager: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        _source(manager, "unknown")
