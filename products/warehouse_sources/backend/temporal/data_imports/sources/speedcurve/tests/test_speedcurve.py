from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.speedcurve import (
    SpeedcurveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.source import SpeedcurveSource
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.speedcurve import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    SpeedcurveResumeConfig,
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


def _run(
    endpoint: str,
    script: list[ScriptedResponse],
    resume_state: SpeedcurveResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    config = SpeedcurveSourceConfig(api_key="fake-key")
    return SourceDriver(SpeedcurveSource(), config).run(endpoint, script, resume_state=resume_state, **inputs)


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
def test_single_page_rows_and_auth(endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]) -> None:
    result = _run(endpoint, [ScriptedResponse(json=body)])

    assert result.rows == expected
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.path == f"/v1/{endpoint}"
    assert request.headers["authorization"] == "Basic ZmFrZS1rZXk6eA=="
    assert dict(request.query) == {}
    if endpoint == "urls":
        assert result.response is not None
        primary_keys = result.response.primary_keys or []
        assert len({tuple(row[key] for key in primary_keys) for row in expected}) == 2


@pytest.mark.parametrize("endpoint", ["tests", "deploys"])
def test_pagination_and_resume_checkpoint(endpoint: str) -> None:
    selector = "data" if endpoint == "tests" else "deploys"
    key = "test_id" if endpoint == "tests" else "deploy_id"
    script: list[ScriptedResponse] = []
    for page in (1, 2):
        body: dict[str, Any] = {selector: [{key: page, "timestamp": int(NOW.timestamp()) - page}]}
        if endpoint == "tests":
            body["meta"] = {"last_page": 2}
        script.append(ScriptedResponse(json=body))
    if endpoint == "deploys":
        script.append(ScriptedResponse(json={selector: []}))

    result = _run(endpoint, script)

    assert [row[key] for row in result.rows] == [1, 2]
    query_params = [dict(request.query) for request in result.requests]
    assert [params["page"] for params in query_params] == (
        [("1",), ("2",)] if endpoint == "tests" else [("1",), ("2",), ("3",)]
    )
    assert all(params["per_page"] == ("100",) for params in query_params)
    assert all(params["end_timestamp"] == (str(int(NOW.timestamp())),) for params in query_params)
    assert [checkpoint.page for checkpoint in result.saved_states] == ([2] if endpoint == "tests" else [2, 3])
    assert all(checkpoint.end_timestamp == int(NOW.timestamp()) for checkpoint in result.saved_states)
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    # The run itself leaves the checkpoint in place; only `on_complete` clears it.
    assert result.final_state == result.saved_states[-1]
    assert result.completed_state is None


@pytest.mark.parametrize("endpoint", ["tests", "deploys"])
def test_resume_preserves_range_when_clock_and_watermark_change(endpoint: str) -> None:
    saved = SpeedcurveResumeConfig(page=4, start_timestamp=1751000000, end_timestamp=1752000000)
    selector = "data" if endpoint == "tests" else "deploys"

    result = _run(
        endpoint,
        [ScriptedResponse(json={selector: []})],
        resume_state=saved,
        should_use_incremental_field=True,
        db_incremental_field_last_value=1780000000,
    )

    assert result.rows == []
    assert dict(result.requests[0].query) == {
        "page": ("4",),
        "per_page": ("100",),
        "start_timestamp": ("1751000000",),
        "end_timestamp": ("1752000000",),
    }
    assert result.saved_states == []


@responses.activate
def test_validation_uses_one_cheap_request() -> None:
    responses.get(BASE_URL + "sites", json={"sites": []})
    assert validate_credentials("fake-key", "v1") == (True, None)
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert parse_qs(urlsplit(request.url).query) == {"median": ["0"]}
    assert request.headers["Authorization"] == "Basic ZmFrZS1rZXk6eA=="


@pytest.mark.parametrize(("status", "expected_message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_auth_errors_map_to_the_actionable_message(status: int, expected_message: str) -> None:
    result = _run("sites", [ScriptedResponse(status=status, json={"status": "error", "message": "denied"})])

    assert isinstance(result.raised, HTTPError)
    mapped = [
        value
        for pattern, value in SpeedcurveSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert mapped == [expected_message]
    assert len(result.requests) == 1


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


@pytest.mark.parametrize("endpoint", ["sites", "urls", "tests", "deploys", "notes", "budgets"])
def test_missing_collection_does_not_silently_empty_table(endpoint: str) -> None:
    result = _run(endpoint, [ScriptedResponse(json={"unexpected": []})])

    assert isinstance(result.raised, ValueError)
    assert "selector" in str(result.raised)
