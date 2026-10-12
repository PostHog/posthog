import json
from collections.abc import Iterable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semaphore import (
    SemaphoreSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.semaphore import SemaphoreResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.settings import (
    AUTH_ERROR,
    NOT_FOUND_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.source import SemaphoreSource

BASE_URL = "https://example.semaphoreci.com/api/v1alpha/"
PROJECT_ID = "00000000-0000-4000-8000-000000000001"
TOKEN = "test-semaphore-token"
SEND = "requests.sessions.Session.send"


@pytest.fixture
def config() -> SemaphoreSourceConfig:
    return SemaphoreSourceConfig(api_token=TOKEN, organization="example", project_id=PROJECT_ID)


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="workflows",
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at",
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def response(body: object, status: int = 200, next_url: str | None = None) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = BASE_URL + "plumber-workflows"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    if next_url:
        result.headers["Link"] = f'<{next_url}>; rel="next"'
    return result


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
    inputs: SourceInputs,
    manager: MagicMock,
    table: str,
    path: str,
    key: str,
    empty_terminal: bool,
) -> None:
    inputs.schema_name = table
    next_url = f"{BASE_URL}{path}?project_id={PROJECT_ID}&page=2"
    first = {key: "row-1", "created_at": {"seconds": 1704067200, "nanos": 123456000}}
    last = [] if empty_terminal else [{key: "row-2", "created_at": "2024-01-02T00:00:00Z"}]
    with patch(SEND, side_effect=[response([first], next_url=next_url), response(last)]) as send:
        result = SemaphoreSource().source_for_pipeline(config, manager, inputs)
        rows = [row for page in cast(Iterable[Any], result.items()) for row in page]
    assert [row[key] for row in rows] == (["row-1"] if empty_terminal else ["row-1", "row-2"])
    assert rows[0]["created_at"] == datetime(2024, 1, 1, 0, 0, 0, 123456, UTC)
    assert result.primary_keys == [key]
    requests = [call.args[0] for call in send.call_args_list]
    assert urlsplit(requests[0].url).path == f"/api/v1alpha/{path}"
    assert parse_qs(urlsplit(requests[0].url).query) == {"project_id": [PROJECT_ID]}
    assert requests[1].url == next_url
    for request in requests:
        assert request.headers["Authorization"] == f"Token {TOKEN}"
        assert request.headers["User-Agent"] == "SemaphoreCI v2.0 Client"
    assert all(call.kwargs["allow_redirects"] is False for call in send.call_args_list)
    assert manager.save_state.call_args_list[0].args[0] == SemaphoreResumeConfig(next_url=next_url)
    assert manager.save_state.call_args_list[-1].args[0] == SemaphoreResumeConfig(completed=True)


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
    inputs: SourceInputs,
    manager: MagicMock,
    table: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    inputs.schema_name = table
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = watermark
    with patch(SEND, return_value=response([])) as send:
        result = SemaphoreSource().source_for_pipeline(config, manager, inputs)
        list(cast(Iterable[Any], result.items()))
    params = parse_qs(urlsplit(cast(str, send.call_args.args[0].url)).query)
    assert params == {"project_id": [PROJECT_ID], **({"created_after": [expected]} if expected else {})}
    if table == "workflows" and incremental:
        assert result.sort_mode == "desc"


@pytest.mark.parametrize("completed", [False, True])
def test_resume_skips_saved_pages(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    completed: bool,
) -> None:
    next_url = f"{BASE_URL}plumber-workflows?project_id={PROJECT_ID}&page=3"
    manager.can_resume.return_value = True
    manager.load_state.return_value = SemaphoreResumeConfig(next_url=next_url, completed=completed)
    with patch(SEND, return_value=response([{"wf_id": "last"}])) as send:
        result = SemaphoreSource().source_for_pipeline(config, manager, inputs)
        rows = [row for page in cast(Iterable[Any], result.items()) for row in page]
    if completed:
        assert rows == []
        send.assert_not_called()
    else:
        assert rows == [{"wf_id": "last"}]
        assert send.call_args.args[0].url == next_url
        manager.save_state.assert_called_once_with(SemaphoreResumeConfig(completed=True))


@pytest.mark.parametrize(
    ("status", "expected_message"),
    [(401, AUTH_ERROR), (403, PERMISSION_ERROR), (404, NOT_FOUND_ERROR)],
)
def test_auth_errors_are_actionable_and_non_retryable(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    status: int,
    expected_message: str,
) -> None:
    source = SemaphoreSource()
    with patch(SEND, return_value=response({}, status)) as send:
        valid, message = source.validate_credentials(config, 1)
    assert valid is False
    assert message == expected_message
    send.assert_called_once()
    with patch(SEND, return_value=response({}, status)) as send:
        result = source.source_for_pipeline(config, manager, inputs)
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], result.items()))
    assert f"{status} Client Error" in str(error.value)
    assert TOKEN not in str(error.value)
    send.assert_called_once()


def test_validation_reads_only_one_page(config: SemaphoreSourceConfig) -> None:
    with patch(SEND, return_value=response([], next_url=BASE_URL + "plumber-workflows?page=2")) as send:
        assert SemaphoreSource().validate_credentials(config, 1) == (True, None)
    send.assert_called_once()
    request: PreparedRequest = send.call_args.args[0]
    assert request.headers["Authorization"] == f"Token {TOKEN}"
    assert parse_qs(urlsplit(cast(str, request.url)).query) == {"project_id": [PROJECT_ID]}


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
    inputs: SourceInputs,
    manager: MagicMock,
    field: str,
    value: str,
) -> None:
    setattr(config, field, value)
    with patch(SEND) as send:
        assert SemaphoreSource().validate_credentials(config, 1)[0] is False
        with pytest.raises(ValueError):
            SemaphoreSource().source_for_pipeline(config, manager, inputs)
    send.assert_not_called()


@pytest.mark.parametrize(
    "next_url", ["https://example.com/steal", "http://example.semaphoreci.com/api/v1alpha/pipelines"]
)
@pytest.mark.parametrize("resumed", [False, True])
def test_pagination_cannot_send_token_to_another_origin(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    next_url: str,
    resumed: bool,
) -> None:
    manager.can_resume.return_value = resumed
    manager.load_state.return_value = SemaphoreResumeConfig(next_url=next_url)
    with patch(SEND, return_value=response([{"wf_id": "first"}], next_url=next_url)) as send:
        result = SemaphoreSource().source_for_pipeline(config, manager, inputs)
        with pytest.raises(ValueError):
            list(cast(Iterable[Any], result.items()))
    assert send.call_count == (0 if resumed else 1)


@pytest.mark.parametrize("body", [{"error": "unexpected"}, None])
def test_malformed_success_does_not_silently_complete(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    body: Any,
) -> None:
    with patch(SEND, return_value=response(body)):
        result = SemaphoreSource().source_for_pipeline(config, manager, inputs)
        with pytest.raises(ValueError):
            list(cast(Iterable[Any], result.items()))
    manager.save_state.assert_not_called()


def test_invalid_watermark_does_not_run_a_full_refresh(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
) -> None:
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "invalid"
    with patch(SEND) as send, pytest.raises(ValueError, match="sync position"):
        SemaphoreSource().source_for_pipeline(config, manager, inputs)
    send.assert_not_called()


def test_invalid_created_at_does_not_save_a_checkpoint(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
) -> None:
    with patch(SEND, return_value=response([{"wf_id": "invalid", "created_at": "invalid"}])):
        result = SemaphoreSource().source_for_pipeline(config, manager, inputs)
        with pytest.raises(ValueError, match="invalid creation time"):
            list(cast(Iterable[Any], result.items()))
    manager.save_state.assert_not_called()
