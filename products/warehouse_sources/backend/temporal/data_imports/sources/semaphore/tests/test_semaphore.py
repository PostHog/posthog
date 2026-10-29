import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semaphore import (
    SemaphoreSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.semaphore import SemaphoreResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.settings import NOT_FOUND_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.source import SemaphoreSource

BASE_URL = "https://example.semaphoreci.com/api/v1alpha/"
PROJECT_ID = "00000000-0000-4000-8000-000000000001"
TOKEN = "test-semaphore-token"


@pytest.fixture
def config() -> SemaphoreSourceConfig:
    return SemaphoreSourceConfig(api_token=TOKEN, organization="example", project_id=PROJECT_ID)


def response(body: object, status: int = 200, next_url: str | None = None) -> ScriptedResponse:
    headers = {"Content-Type": "application/json"}
    if next_url:
        headers["Link"] = f'<{next_url}>; rel="next"'
    return ScriptedResponse(status=status, body=json.dumps(body).encode(), headers=headers)


@pytest.mark.parametrize(
    ("table", "path", "key"),
    [
        ("workflows", "plumber-workflows", "wf_id"),
        ("pipelines", "pipelines", "ppl_id"),
        ("deployment_targets", "deployment_targets", "id"),
    ],
)
@pytest.mark.parametrize("empty_terminal", [False, True])
def test_transport_and_terminal_page(
    config: SemaphoreSourceConfig,
    table: str,
    path: str,
    key: str,
    empty_terminal: bool,
) -> None:
    next_url = f"{BASE_URL}{path}?project_id={PROJECT_ID}&page=2"
    first = {key: "row-1", "created_at": {"seconds": 1704067200, "nanos": 123456000}}
    last = [] if empty_terminal else [{key: "row-2", "created_at": "2024-01-02T00:00:00Z"}]
    result = SourceDriver(SemaphoreSource(), config).run(table, [response([first], next_url=next_url), response(last)])
    rows = result.rows
    assert [row[key] for row in rows] == (["row-1"] if empty_terminal else ["row-1", "row-2"])
    assert rows[0]["created_at"] == datetime(2024, 1, 1, 0, 0, 0, 123456, UTC)
    assert result.response is not None
    assert result.response.primary_keys == [key]
    requests = result.requests
    assert urlsplit(requests[0].url).path == f"/api/v1alpha/{path}"
    assert parse_qs(urlsplit(requests[0].url).query) == {"project_id": [PROJECT_ID]}
    assert requests[1].url == next_url
    for request in requests:
        assert request.headers["authorization"] == f"Token {TOKEN}"
        assert request.headers["user-agent"] == "SemaphoreCI v2.0 Client"
    assert result.saved_states[0] == SemaphoreResumeConfig(next_url=next_url)
    assert result.saved_states[-1] == SemaphoreResumeConfig(completed=True)


@pytest.mark.parametrize(
    ("table", "incremental", "watermark", "expected"),
    [
        ("workflows", True, datetime(2024, 1, 1, tzinfo=UTC), "1704067199"),
        ("workflows", True, "2024-01-01T00:00:00.999999Z", "1704067199"),
        ("workflows", True, None, None),
        ("workflows", False, "2024-01-01T00:00:00Z", None),
        ("pipelines", True, "2024-01-01T00:00:00Z", None),
        ("deployment_targets", True, "2024-01-01T00:00:00Z", None),
    ],
)
def test_incremental_filter(
    config: SemaphoreSourceConfig,
    table: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        table,
        [response([])],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )
    params = parse_qs(urlsplit(result.requests[-1].url).query)
    assert params == {"project_id": [PROJECT_ID], **({"created_after": [expected]} if expected else {})}
    if table == "workflows" and incremental:
        assert result.response is not None
        assert result.response.sort_mode == "desc"


@pytest.mark.parametrize("completed", [False, True])
def test_resume_skips_saved_pages(config: SemaphoreSourceConfig, completed: bool) -> None:
    next_url = f"{BASE_URL}plumber-workflows?project_id={PROJECT_ID}&page=3"
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows",
        [response([{"wf_id": "last"}])],
        resume_state=SemaphoreResumeConfig(next_url=next_url, completed=completed),
    )
    if completed:
        assert result.rows == []
        assert result.requests == []
    else:
        assert result.rows == [{"wf_id": "last"}]
        assert result.requests[-1].url == next_url
        assert result.saved_states == [SemaphoreResumeConfig(completed=True)]


@pytest.mark.parametrize(
    ("status", "expected_message"),
    [(404, NOT_FOUND_ERROR)],
)
def test_auth_errors_are_actionable_and_non_retryable(
    config: SemaphoreSourceConfig,
    status: int,
    expected_message: str,
) -> None:
    source = SemaphoreSource()
    with scripted_network([response({}, status)]) as network:
        valid, message = source.validate_credentials(config, 1)
    assert valid is False
    assert message == expected_message
    assert len(network.requests_log) == 1
    result = SourceDriver(source, config).run("workflows", [response({}, status)])
    assert isinstance(result.raised, HTTPError)
    assert f"{status} Client Error" in str(result.raised)
    assert TOKEN not in str(result.raised)
    assert len(result.requests) == 1


def test_validation_reads_only_one_page(config: SemaphoreSourceConfig) -> None:
    with scripted_network([response([], next_url=BASE_URL + "plumber-workflows?page=2")]) as network:
        assert SemaphoreSource().validate_credentials(config, 1) == (True, None)
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["authorization"] == f"Token {TOKEN}"
    assert parse_qs(urlsplit(request.url).query) == {"project_id": [PROJECT_ID]}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization", "https://example.com"),
        ("organization", "example.com"),
        ("organization", "example@evil.com"),
        ("organization", "bad\n"),
        ("organization", "-bad"),
        ("organization", "a" * 64),
        ("project_id", "not-a-uuid"),
    ],
)
def test_invalid_configuration_never_sends_credentials(
    config: SemaphoreSourceConfig,
    field: str,
    value: str,
) -> None:
    setattr(config, field, value)
    with scripted_network([]) as network:
        assert SemaphoreSource().validate_credentials(config, 1)[0] is False
    result = SourceDriver(SemaphoreSource(), config).run("workflows", [])
    assert isinstance(result.raised, ValueError)
    assert network.requests_log == []
    assert result.requests == []


@pytest.mark.parametrize(
    "next_url", ["https://example.com/steal", "http://example.semaphoreci.com/api/v1alpha/pipelines"]
)
@pytest.mark.parametrize("resumed", [False, True])
def test_pagination_cannot_send_token_to_another_origin(
    config: SemaphoreSourceConfig,
    next_url: str,
    resumed: bool,
) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows",
        [response([{"wf_id": "first"}], next_url=next_url)],
        resume_state=SemaphoreResumeConfig(next_url=next_url) if resumed else None,
    )
    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == (0 if resumed else 1)


@pytest.mark.parametrize("body", [{"error": "unexpected"}, None])
def test_malformed_success_does_not_silently_complete(config: SemaphoreSourceConfig, body: Any) -> None:
    result = SourceDriver(SemaphoreSource(), config).run("workflows", [response(body)])
    assert isinstance(result.raised, ValueError)
    assert result.saved_states == []


def test_invalid_watermark_does_not_run_a_full_refresh(config: SemaphoreSourceConfig) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows", [], should_use_incremental_field=True, db_incremental_field_last_value="invalid"
    )
    assert isinstance(result.raised, ValueError)
    assert "sync position" in str(result.raised)
    assert result.requests == []


def test_invalid_created_at_does_not_save_a_checkpoint(config: SemaphoreSourceConfig) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows", [response([{"wf_id": "invalid", "created_at": "invalid"}])]
    )
    assert isinstance(result.raised, ValueError)
    assert "invalid creation time" in str(result.raised)
    assert result.saved_states == []


def test_redirects_are_not_followed(config: SemaphoreSourceConfig) -> None:
    result = SourceDriver(SemaphoreSource(), config).run(
        "workflows",
        [ScriptedResponse(status=302, headers={"Location": "https://example.com/steal"}, json={})],
    )
    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 1
