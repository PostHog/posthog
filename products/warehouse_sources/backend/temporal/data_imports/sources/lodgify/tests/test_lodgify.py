import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lodgify.lodgify import (
    LodgifyResumeConfig,
    lodgify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lodgify.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lodgify.source import LodgifySource


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            side_effect=lambda **kwargs: Session(),
        ),
        patch.object(Session, "send") as send,
    ):
        yield send


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = {401: "Unauthorized", 403: "Forbidden"}.get(status, "Test response")
    result.url = "https://api.lodgify.com/v2/properties"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    result.headers["Retry-After"] = "0"
    return result


@pytest.mark.parametrize("endpoint", ["properties", "bookings"])
@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (False, "2026-01-01T00:00:00Z", None),
        (True, None, None),
        (True, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00+00:00"),
        (True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00+00:00"),
    ],
)
def test_sync_parameters(
    transport: MagicMock,
    manager: MagicMock,
    endpoint: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    transport.side_effect = [response({"items": [{"id": 1}]}), response({"items": []})]
    result = lodgify_source("test-key", endpoint, 1, "job", manager, incremental, watermark)
    list(cast(Iterable[Any], result.items()))
    assert result.sort_mode == "desc"
    for call in transport.call_args_list:
        params = parse_qs(urlsplit(call.args[0].url).query)
        assert params.get("updatedSince") == ([expected] if expected else None)
        if endpoint == "bookings":
            assert params["stayFilter"] == ["All"]
            assert params["trash"] == ["All"]
            assert params["includeTransactions"] == ["true"]
            assert params["includeQuoteDetails"] == ["true"]


@pytest.mark.parametrize("resume", [False, True])
def test_room_fanout(transport: MagicMock, manager: MagicMock, resume: bool) -> None:
    manager.can_resume.return_value = resume
    manager.load_state.return_value = LodgifyResumeConfig(
        paginator_state={"completed": ["properties/10/rooms"], "current": None, "child_state": None}
    )
    transport.side_effect = [
        response({"items": [{"id": 10}, {"id": 20}, {"id": 30}]}),
        *([] if resume else [response([{"id": 1, "name": "Room one"}])]),
        response([{"id": 1, "name": "Room two"}]),
        response([]),
        response({"items": []}),
    ]
    result = lodgify_source("test-key", "rooms", 1, "job", manager, True, "2026-01-01T00:00:00Z")
    rows = [row for page in cast(Iterable[Any], result.items()) for row in page]
    assert rows == [
        *([] if resume else [{"id": 1, "name": "Room one", "property_id": 10}]),
        {"id": 1, "name": "Room two", "property_id": 20},
    ]
    assert result.primary_keys == ["property_id", "id"]
    paths = [urlsplit(call.args[0].url).path for call in transport.call_args_list]
    assert paths == [
        "/v2/properties",
        *([] if resume else ["/v2/properties/10/rooms"]),
        "/v2/properties/20/rooms",
        "/v2/properties/30/rooms",
        "/v2/properties",
    ]
    for call in transport.call_args_list:
        assert "updatedSince" not in parse_qs(urlsplit(call.args[0].url).query)
    assert manager.save_state.call_args.args[0].paginator_state["completed"] == [
        "properties/10/rooms",
        "properties/20/rooms",
        "properties/30/rooms",
    ]


@pytest.mark.parametrize(
    "status,expected", [(200, (True, None)), (401, (False, AUTH_ERROR)), (403, (False, PERMISSION_ERROR))]
)
def test_credential_validation(transport: MagicMock, status: int, expected: tuple[bool, str | None]) -> None:
    transport.return_value = response({"items": []}, status)
    assert validate_credentials("test-key") == expected
    transport.assert_called_once()
    request = transport.call_args.args[0]
    assert request.headers["X-ApiKey"] == "test-key"
    assert parse_qs(urlsplit(request.url).query) == {"page": ["1"], "size": ["1"]}


@pytest.mark.parametrize("status", [401, 403, 400, 404])
def test_permanent_errors(transport: MagicMock, manager: MagicMock, status: int) -> None:
    transport.return_value = response({}, status)
    with pytest.raises(HTTPError) as exc:
        list(cast(Iterable[Any], lodgify_source("test-key", "properties", 1, "job", manager).items()))
    matches = [
        message for pattern, message in LodgifySource().get_non_retryable_errors().items() if pattern in str(exc.value)
    ]
    assert matches == ([AUTH_ERROR] if status == 401 else [PERMISSION_ERROR] if status == 403 else [])
    transport.assert_called_once()


@pytest.mark.parametrize("status", [400, 404])
def test_validation_propagates_other_errors(transport: MagicMock, status: int) -> None:
    transport.return_value = response({}, status)
    with pytest.raises(HTTPError):
        validate_credentials("test-key")
    transport.assert_called_once()


@pytest.mark.parametrize(
    "endpoint,watermark,message",
    [
        ("unknown", None, "Unsupported Lodgify table"),
        ("properties", "invalid", "Invalid Lodgify sync timestamp"),
    ],
)
def test_invalid_inputs(manager: MagicMock, endpoint: str, watermark: str | None, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        lodgify_source("test-key", endpoint, 1, "job", manager, True, watermark)


def test_missing_response_list_fails(transport: MagicMock, manager: MagicMock) -> None:
    transport.return_value = response({"unexpected": []})
    with pytest.raises(ValueError):
        list(cast(Iterable[Any], lodgify_source("test-key", "properties", 1, "job", manager).items()))
