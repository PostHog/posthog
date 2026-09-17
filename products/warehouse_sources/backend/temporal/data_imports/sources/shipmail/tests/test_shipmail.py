import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.shipmail import (
    SHIPMAIL_BASE_URL,
    ShipmailResumeConfig,
    _incremental_value,
    get_capabilities,
    shipmail_source,
)

TRACKED_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shipmail.shipmail.make_tracked_session"
)


def _response(body: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _manager(resume_state: ShipmailResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    params: list[dict[str, Any]] = []

    def prepare(request: Any) -> mock.MagicMock:
        params.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = prepare
    session.send.side_effect = responses
    return params


def _source(endpoint: str, manager: mock.MagicMock, **overrides: Any):
    return shipmail_source(
        "test-key",
        endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
        **overrides,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def test_incremental_value_preserves_iso_timestamp() -> None:
    value = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)
    assert _incremental_value(value) == "2026-07-29T12:30:00+00:00"
    assert _incremental_value("2026-07-29T12:30:00Z") == "2026-07-29T12:30:00Z"


@mock.patch(TRACKED_SESSION_PATCH)
def test_messages_paginates_checkpoints_and_sends_incremental_watermark(make_session: mock.MagicMock) -> None:
    session = make_session.return_value
    params = _wire(
        session,
        [
            _response(
                {
                    "data": [{"id": "msg_1"}],
                    "pagination": {"next_cursor": "cursor_2", "has_more": True, "limit": 100},
                }
            ),
            _response(
                {
                    "data": [{"id": "msg_2"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            ),
        ],
    )
    manager = _manager()

    rows = _rows(
        _source(
            "messages",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01T00:00:00Z",
            incremental_field="updated_at",
        )
    )

    assert rows == [{"id": "msg_1"}, {"id": "msg_2"}]
    assert params[0] == {"limit": 100, "updated_after": "2026-07-01T00:00:00Z"}
    assert params[1] == {
        "limit": 100,
        "updated_after": "2026-07-01T00:00:00Z",
        "cursor": "cursor_2",
    }
    manager.save_state.assert_called_once_with(ShipmailResumeConfig(cursor="cursor_2"))
    make_session.assert_called_once_with(redact_values=("test-key",), capture=False)


@mock.patch(TRACKED_SESSION_PATCH)
def test_resumes_from_saved_cursor(make_session: mock.MagicMock) -> None:
    session = make_session.return_value
    params = _wire(
        session,
        [
            _response(
                {
                    "data": [{"id": "mbx_2"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            )
        ],
    )

    rows = _rows(_source("mailboxes", _manager(ShipmailResumeConfig(cursor="cursor_2"))))

    assert rows == [{"id": "mbx_2"}]
    assert params[0] == {"limit": 100, "cursor": "cursor_2"}


@mock.patch(TRACKED_SESSION_PATCH)
def test_full_refresh_endpoint_does_not_send_incremental_watermark(make_session: mock.MagicMock) -> None:
    session = make_session.return_value
    params = _wire(
        session,
        [
            _response(
                {
                    "data": [{"id": "domain_1"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            )
        ],
    )

    _rows(
        _source(
            "domains",
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01T00:00:00Z",
            incremental_field="updated_at",
        )
    )

    assert params[0] == {"limit": 100}


@mock.patch(TRACKED_SESSION_PATCH)
def test_missing_data_key_raises(make_session: mock.MagicMock) -> None:
    session = make_session.return_value
    _wire(session, [_response({"pagination": {"next_cursor": None}})])

    with pytest.raises(ValueError, match="matched nothing"):
        _rows(_source("messages", _manager()))


@pytest.mark.parametrize(
    ("endpoint", "primary_keys", "sort_mode"),
    [
        ("messages", ["id"], "asc"),
        ("mailboxes", ["id"], "desc"),
        ("domains", ["id"], "desc"),
        ("suppressions", ["email_address"], "desc"),
    ],
)
def test_source_response_metadata(endpoint: str, primary_keys: list[str], sort_mode: str) -> None:
    response = _source(endpoint, _manager())
    assert response.primary_keys == primary_keys
    assert response.partition_keys == ["created_at"]
    assert response.partition_format == "month"
    assert response.sort_mode == sort_mode


@mock.patch(TRACKED_SESSION_PATCH)
def test_get_capabilities_returns_status_and_scopes(make_session: mock.MagicMock) -> None:
    session = make_session.return_value
    session.get.return_value = _response({"scopes": ["messages:read", "domains:read"]})

    assert get_capabilities("secret-key") == (200, {"messages:read", "domains:read"})
    session.get.assert_called_once_with(
        f"{SHIPMAIL_BASE_URL}/capabilities",
        headers={"Authorization": "Bearer secret-key", "Accept": "application/json"},
        timeout=10,
    )
    make_session.assert_called_once_with(redact_values=("secret-key",), capture=False)


@mock.patch(TRACKED_SESSION_PATCH)
def test_get_capabilities_handles_invalid_credentials(make_session: mock.MagicMock) -> None:
    make_session.return_value.get.return_value = _response({"error": "unauthorized"}, status_code=401)
    assert get_capabilities("bad-key") == (401, set())
