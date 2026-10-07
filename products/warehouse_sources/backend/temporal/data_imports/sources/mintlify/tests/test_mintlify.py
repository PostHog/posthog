import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mintlify import (
    MintlifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.mintlify import (
    MintlifyResumeConfig,
    mintlify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.source import MintlifySource


@pytest.fixture
def config() -> MintlifySourceConfig:
    return MintlifySourceConfig(api_key="mint_example_fake_key", project_id="example-project")


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    with Session() as session:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
                return_value=session,
            ),
            patch.object(session, "send") as send,
        ):
            yield send


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://api.mintlify.com/v1/analytics/example-project/feedback"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


@pytest.mark.parametrize(
    ("endpoint", "path", "selector", "limit", "row"),
    [
        (
            "assistant_conversations",
            "assistant",
            "conversations",
            1000,
            {"id": "turn-1", "timestamp": "2026-01-01T00:00:00Z"},
        ),
        ("feedback", "feedback", "feedback", 100, {"id": "feedback-1", "createdAt": None, "status": "pending"}),
        ("searches", "searches", "searches", 100, {"searchQuery": "setup", "hits": 12}),
    ],
)
def test_cursor_pages(
    config: MintlifySourceConfig,
    manager: MagicMock,
    transport: MagicMock,
    endpoint: str,
    path: str,
    selector: str,
    limit: int,
    row: dict[str, Any],
) -> None:
    transport.side_effect = [
        response({selector: [row], "nextCursor": "cursor-2", "hasMore": True}),
        response({selector: [], "nextCursor": "cursor-3", "hasMore": True}),
        response({selector: [row], "nextCursor": None, "hasMore": False}),
    ]
    source = mintlify_source(config, endpoint, 1, "job", manager)
    assert list(cast(Iterable[Any], source.items())) == [[row], [row]]
    requests = [cast(PreparedRequest, call.args[0]) for call in transport.call_args_list]
    params = [parse_qs(urlsplit(cast(str, request.url)).query) for request in requests]
    assert [param.get("cursor") for param in params] == [None, ["cursor-2"], ["cursor-3"]]
    assert all(param["limit"] == [str(limit)] for param in params)
    assert all(param["dateTo"] == params[0]["dateTo"] for param in params)
    assert all("dateFrom" not in param for param in params)
    assert all(urlsplit(cast(str, request.url)).path == f"/v1/analytics/example-project/{path}" for request in requests)
    assert all(request.headers["Authorization"] == "Bearer mint_example_fake_key" for request in requests)
    assert [call.args[0].paginator_state for call in manager.save_state.call_args_list] == [
        {"cursor": "cursor-2"},
        {"cursor": "cursor-3"},
    ]


@pytest.mark.parametrize("endpoint", ["views", "visitors"])
@pytest.mark.parametrize("terminal_rows", [[], [{"path": "/last", "human": 1, "ai": 0, "total": 1}]])
def test_offset_pages_use_has_more(
    config: MintlifySourceConfig,
    manager: MagicMock,
    transport: MagicMock,
    endpoint: str,
    terminal_rows: list[dict[str, Any]],
) -> None:
    row = {"path": "/start", "human": 3, "ai": 2, "total": 5}
    transport.side_effect = [
        response({endpoint: [row], "hasMore": True, "totals": {"total": 5}}),
        response({endpoint: [], "hasMore": True}),
        response({endpoint: terminal_rows, "hasMore": False}),
    ]
    source = mintlify_source(config, endpoint, 1, "job", manager)
    assert [item for page in cast(Iterable[Any], source.items()) for item in page] == [row, *terminal_rows]
    params = [parse_qs(urlsplit(call.args[0].url).query) for call in transport.call_args_list]
    assert [param["offset"] for param in params] == [["0"], ["250"], ["500"]]
    assert all(param["limit"] == ["250"] for param in params)
    assert [call.args[0].paginator_state for call in manager.save_state.call_args_list] == [
        {"offset": 250},
        {"offset": 500},
    ]


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected"),
    [
        (True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00+00:00"),
        (True, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        (True, None, None),
        (False, "2026-01-01T00:00:00Z", None),
    ],
)
def test_incremental_date_filter(
    config: MintlifySourceConfig,
    manager: MagicMock,
    transport: MagicMock,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    transport.side_effect = [
        response({"conversations": [{"id": "turn-1"}], "nextCursor": "cursor-2"}),
        response({"conversations": [], "nextCursor": None}),
    ]
    source = mintlify_source(config, "assistant_conversations", 1, "job", manager, incremental, watermark)
    list(cast(Iterable[Any], source.items()))
    for call in transport.call_args_list:
        params = parse_qs(urlsplit(call.args[0].url).query)
        assert params.get("dateFrom") == ([expected] if expected else None)
    if incremental:
        assert source.sort_mode == "desc"


@pytest.mark.parametrize(
    ("endpoint", "selector", "state", "parameter", "value"),
    [
        ("assistant_conversations", "conversations", {"cursor": "saved-cursor"}, "cursor", "saved-cursor"),
        ("views", "views", {"offset": 750}, "offset", "750"),
    ],
)
def test_resume_preserves_window(
    config: MintlifySourceConfig,
    manager: MagicMock,
    transport: MagicMock,
    endpoint: str,
    selector: str,
    state: dict[str, Any],
    parameter: str,
    value: str,
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = MintlifyResumeConfig(
        paginator_state=state, date_to="2026-01-02T00:00:00Z", date_from=None
    )
    transport.return_value = response({selector: [], "nextCursor": None, "hasMore": False})
    list(cast(Iterable[Any], mintlify_source(config, endpoint, 1, "job", manager).items()))
    request = cast(PreparedRequest, transport.call_args.args[0])
    params = parse_qs(urlsplit(cast(str, request.url)).query)
    assert params[parameter] == [value]
    assert params["dateTo"] == ["2026-01-02T00:00:00Z"]
    assert "dateFrom" not in params
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status", [200, 400, 401, 403, 404])
def test_credentials_and_terminal_errors(config: MintlifySourceConfig, transport: MagicMock, status: int) -> None:
    body: dict[str, Any] = {"feedback": []} if status == 200 else {"error": "Unauthorized"}
    transport.return_value = response(body, status)
    valid, message = validate_credentials(config)
    assert valid is (status == 200)
    if status != 200:
        assert message
        assert message == MintlifySource().get_non_retryable_errors()[f"{status} Client Error"]
    transport.assert_called_once()
    request = cast(PreparedRequest, transport.call_args.args[0])
    assert request.headers["Authorization"] == "Bearer mint_example_fake_key"
    assert parse_qs(urlsplit(cast(str, request.url)).query) == {"limit": ["1"]}


@pytest.mark.parametrize("status", [429, 500])
def test_transient_errors_stay_retryable(config: MintlifySourceConfig, transport: MagicMock, status: int) -> None:
    transport.return_value = response({"error": "Unavailable"}, status)
    with patch.object(RESTClient, "_send_request", cast(Any, RESTClient._send_request).__wrapped__):
        with pytest.raises(RESTClientRetryableError):
            validate_credentials(config)
    assert not any(str(status) in key for key in MintlifySource().get_non_retryable_errors())


def test_unknown_table_fails_before_request(
    config: MintlifySourceConfig, manager: MagicMock, transport: MagicMock
) -> None:
    with pytest.raises(UnknownResourceError):
        mintlify_source(config, "unknown", 1, "job", manager)
    with pytest.raises(UnknownResourceError):
        validate_credentials(config, "unknown")
    transport.assert_not_called()


def test_project_id_cannot_change_request_path(
    config: MintlifySourceConfig, manager: MagicMock, transport: MagicMock
) -> None:
    config.project_id = "example/other?limit=5#fragment"
    transport.return_value = response({"feedback": [], "nextCursor": None})
    list(cast(Iterable[Any], mintlify_source(config, "feedback", 1, "job", manager).items()))
    request = cast(PreparedRequest, transport.call_args.args[0])
    url = urlsplit(cast(str, request.url))
    assert url.netloc == "api.mintlify.com"
    assert url.path == "/v1/analytics/example%2Fother%3Flimit%3D5%23fragment/feedback"
    assert parse_qs(url.query)["limit"] == ["100"]


def test_source_adapter_delegates_to_mintlify_transport(config: MintlifySourceConfig) -> None:
    source = MintlifySource()
    inputs = MagicMock(
        schema_name="assistant_conversations",
        team_id=1,
        job_id="job",
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
    )
    manager = source.get_resumable_source_manager(inputs)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.source.validate_credentials",
        return_value=(True, None),
    ) as validate:
        assert source.validate_credentials(config, 1, "feedback") == (True, None)
        validate.assert_called_once_with(config, "feedback")

    expected = MagicMock()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.source.mintlify_source",
        return_value=expected,
    ) as build_source:
        assert source.source_for_pipeline(config, manager, inputs) is expected
        build_source.assert_called_once_with(
            config=config,
            endpoint_name="assistant_conversations",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
