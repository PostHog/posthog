import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scalr import ScalrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scalr.scalr import ScalrResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scalr.source import ScalrSource

MIXINS = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"


@pytest.fixture
def config() -> ScalrSourceConfig:
    return ScalrSourceConfig(host="scalr.example.com", account_id="acc-example", api_token="fake-token")


@pytest.fixture
def send() -> Iterator[MagicMock]:
    with (
        patch("requests.sessions.Session.send") as mock_send,
        patch(f"{MIXINS}.is_cloud", return_value=True),
        patch(f"{MIXINS}.get_instance_region", return_value="US"),
        patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]),
    ):
        yield mock_send


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.url = "https://scalr.example.com/api/iacp/v3/environments"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/vnd.api+json"
    return result


def page(endpoint: str, identifier: str | None, next_page: int | None) -> Response:
    return response(
        {
            "data": [
                {
                    "id": identifier,
                    "type": endpoint,
                    "attributes": {
                        "created-at": "2025-01-01T00:00:00Z",
                        "updated-at": "2025-01-02T00:00:00Z",
                        "name": "Example",
                    },
                    "relationships": {"account": {"data": {"id": "acc-example", "type": "accounts"}}},
                }
            ]
            if identifier
            else [],
            "meta": {"pagination": {"next-page": next_page}},
        }
    )


def inputs(endpoint: str, incremental: bool = False, watermark: datetime | str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=endpoint,
        schema_id="schema-example",
        source_id="source-example",
        team_id=123,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="updated_at" if incremental else None,
        incremental_field_type=None,
        job_id="job-example",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def manager(next_page: str | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = next_page is not None
    result.load_state.return_value = ScalrResumeConfig(next_page=next_page) if next_page else None
    return result


@pytest.mark.parametrize("endpoint", ["environments", "workspaces", "runs"])
@pytest.mark.parametrize("resume_page", [None, "3"])
def test_pagination_auth_and_resume(
    config: ScalrSourceConfig, send: MagicMock, endpoint: str, resume_page: str | None
) -> None:
    first_page = int(resume_page or "1")
    send.side_effect = [page(endpoint, "item-1", first_page + 1), page(endpoint, "item-2", None)]
    checkpoint = manager(resume_page)
    result = ScalrSource().source_for_pipeline(config, checkpoint, inputs(endpoint))
    iterator = iter(cast(Iterable[Any], result.items()))
    first_batch = next(iterator)
    rows = first_batch + [row for batch in iterator for row in batch]
    checkpoint.save_state.assert_called_once_with(ScalrResumeConfig(next_page=str(first_page + 1)))
    assert [row["id"] for row in rows] == ["item-1", "item-2"]
    assert rows[0]["created_at"] == datetime(2025, 1, 1, tzinfo=UTC)
    assert rows[0]["relationships"]["account"]["data"]["id"] == "acc-example"
    assert send.call_count == 2
    for index, call in enumerate(send.call_args_list):
        request = call.args[0]
        assert request.method == "GET"
        assert urlsplit(request.url).path == f"/api/iacp/v3/{endpoint}"
        params = parse_qs(urlsplit(request.url).query)
        assert params["page[number]"] == [str(first_page + index)]
        assert params["page[size]"] == ["50"]
        assert params["filter[account]"] == ["acc-example"]
        assert request.headers["Authorization"] == "Bearer fake-token"
        assert request.headers["Accept"] == "application/vnd.api+json"
        assert call.kwargs["allow_redirects"] is False
        assert call.kwargs["timeout"] == 30
    checkpoint.save_state.assert_called_once()


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected"),
    [
        (False, "2025-01-01T00:00:00Z", None),
        (True, None, None),
        (True, "2025-01-01T00:00:00Z", "gte:2025-01-01T00:00:00Z"),
        (True, datetime(2025, 1, 1, tzinfo=UTC), "gte:2025-01-01T00:00:00+00:00"),
    ],
)
def test_workspace_filter_on_every_page(
    config: ScalrSourceConfig,
    send: MagicMock,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    send.side_effect = [page("workspaces", "ws-1", 2), page("workspaces", None, None)]
    result = ScalrSource().source_for_pipeline(config, manager(), inputs("workspaces", incremental, watermark))
    list(cast(Iterable[Any], result.items()))
    assert result.sort_mode == "asc"
    for call in send.call_args_list:
        params = parse_qs(urlsplit(call.args[0].url).query)
        assert params["sort"] == ["updated-at"]
        assert params.get("filter[updated-at]") == ([expected] if expected else None)
    assert send.call_count == 2


@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_errors_are_non_retryable(config: ScalrSourceConfig, send: MagicMock, status: int) -> None:
    send.return_value = response({"errors": [{"status": str(status)}]}, status)
    source = ScalrSource()
    valid, error = source.validate_credentials(config, team_id=123)
    assert not valid
    assert error == source.get_non_retryable_errors()[f"{status} Client Error"]
    assert send.call_count == 1
    with pytest.raises(HTTPError, match=f"{status} Client Error"):
        list(cast(Iterable[Any], source.source_for_pipeline(config, manager(), inputs("environments")).items()))
    assert send.call_count == 2


def test_validation_uses_one_small_page(config: ScalrSourceConfig, send: MagicMock) -> None:
    send.return_value = page("environments", "env-1", 2)
    assert ScalrSource().validate_credentials(config, team_id=123) == (True, None)
    send.assert_called_once()
    params = parse_qs(urlsplit(send.call_args.args[0].url).query)
    assert params == {"filter[account]": ["acc-example"], "page[size]": ["1"]}


@pytest.mark.parametrize("body", [{"errors": [{"title": "Unexpected result"}]}, {"data": {"id": "wrong-shape"}}])
def test_malformed_response_fails(config: ScalrSourceConfig, send: MagicMock, body: dict[str, Any]) -> None:
    send.return_value = response(body)
    with pytest.raises(ValueError):
        list(cast(Iterable[Any], ScalrSource().source_for_pipeline(config, manager(), inputs("runs")).items()))
    send.assert_called_once()


def test_empty_first_page_finishes(config: ScalrSourceConfig, send: MagicMock) -> None:
    send.return_value = page("runs", None, None)
    checkpoint = manager()
    assert (
        list(cast(Iterable[Any], ScalrSource().source_for_pipeline(config, checkpoint, inputs("runs")).items())) == []
    )
    checkpoint.save_state.assert_not_called()
    send.assert_called_once()


@pytest.mark.parametrize(
    "host",
    [
        "http://scalr.example.com",
        "scalr.example.com/path",
        "user@scalr.example.com",
        "scalr.example.com:443",
        "localhost",
        "127.0.0.1",
        "169.254.169.254",
    ],
)
def test_invalid_host_sends_no_token(config: ScalrSourceConfig, send: MagicMock, host: str) -> None:
    config.host = host
    valid, error = ScalrSource().validate_credentials(config, team_id=123)
    assert not valid
    assert error
    with pytest.raises(ValueError):
        ScalrSource().source_for_pipeline(config, manager(), inputs("runs"))
    send.assert_not_called()


def test_private_dns_sends_no_token(config: ScalrSourceConfig, send: MagicMock) -> None:
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 443))]):
        valid, error = ScalrSource().validate_credentials(config, team_id=123)
    assert not valid
    assert error
    send.assert_not_called()


def test_redirect_is_rejected(config: ScalrSourceConfig, send: MagicMock) -> None:
    redirect = response({}, 302)
    redirect.headers["Location"] = "http://internal.example.com"
    send.return_value = redirect
    valid, error = ScalrSource().validate_credentials(config, team_id=123)
    assert not valid
    assert error and "refusing to follow" in error
    send.assert_called_once()


@pytest.mark.parametrize(("endpoint", "field"), [("runs", "created_at"), ("workspaces", "created_at")])
def test_unsupported_incremental_field_fails(
    config: ScalrSourceConfig, send: MagicMock, endpoint: str, field: str
) -> None:
    source_inputs = inputs(endpoint, incremental=True)
    source_inputs.incremental_field = field
    with pytest.raises(ValueError, match="only for the workspace updated_at"):
        ScalrSource().source_for_pipeline(config, manager(), source_inputs)
    send.assert_not_called()
