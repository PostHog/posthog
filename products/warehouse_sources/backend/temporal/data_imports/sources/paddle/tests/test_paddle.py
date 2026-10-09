import json
from datetime import datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paddle import PaddleSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PADDLE_BASE_URL,
    PaddlePermissionError,
    PaddleResumeConfig,
    PaddleUnreachableError,
    _format_paddle_datetime_query_value,
    paddle_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source import (
    INVALID_API_KEY_ERROR,
    KEY_CHECK_FAILED_ERROR,
    MISSING_PERMISSIONS_ERROR,
    PaddleSource,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the paddle module.
PADDLE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.make_tracked_session"
)
SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source"


def _response(
    items: list[dict[str, Any]] | None,
    *,
    next_url: str | None = None,
    has_more: bool | None = None,
    drop_data: bool = False,
) -> Response:
    # Real Paddle bodies always carry has_more; default it from next_url so fixture
    # pages terminate the way real responses do (via has_more, not a null next).
    if has_more is None:
        has_more = next_url is not None
    body: dict[str, Any] = {"meta": {"pagination": {"per_page": 200, "next": next_url, "has_more": has_more}}}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: PaddleResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session, capturing each request's params AND url AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return paddle_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_body_next_url_and_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{PADDLE_BASE_URL}/customers?after=c_1"
        params, urls = _wire(
            session,
            [
                _response([{"id": "c_1"}], next_url=next_url),
                _response([{"id": "c_2"}], next_url=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["id"] for r in rows] == ["c_1", "c_2"]
        # First request hits the base path with list params; second follows the self-contained next URL.
        assert params[0]["per_page"] == 200
        assert params[0]["order_by"] == "id[ASC]"
        assert urls[0] == f"{PADDLE_BASE_URL}/customers"
        assert urls[1] == next_url
        # The next URL already carries every query param, so the follow-up request drops the originals.
        assert params[1] == {}


class TestIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_field_adds_server_side_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": "t_1"}], next_url=None)])

        manager = _make_manager()
        _rows(
            _source(
                "transactions",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-02T03:04:05Z",
            )
        )

        assert params[0]["order_by"] == "billed_at[ASC]"
        assert params[0]["billed_at[GT]"] == "2024-01-02T03:04:05Z"


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_saved_on_last_page_terminates_on_resume(self, MockSession) -> None:
        # A checkpoint saved while looping on the final page points at that page.
        # The resumed fetch sees has_more=false, completes, and writes the empty
        # terminal marker instead of re-saving the same URL.
        session = MockSession.return_value
        saved_url = f"{PADDLE_BASE_URL}/customers?after=c_9"
        _wire(session, [_response([], next_url=saved_url, has_more=False)])

        manager = _make_manager(PaddleResumeConfig(next_url=saved_url))
        rows = _rows(_source("customers", manager))

        assert rows == []
        assert session.send.call_count == 1
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [PaddleResumeConfig(next_url="")]


class TestValidateCredentials:
    @mock.patch(PADDLE_SESSION_PATCH)
    def test_permission_error_on_403(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=403)
        with pytest.raises(PaddlePermissionError, match="Missing permissions for"):
            validate_credentials("key")

    @mock.patch(PADDLE_SESSION_PATCH)
    def test_transport_failure_is_not_a_rejected_key(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        with pytest.raises(PaddleUnreachableError):
            validate_credentials("key")


class TestSourceValidateCredentials:
    def _validate(self) -> tuple[bool, str | None]:
        return PaddleSource().validate_credentials(PaddleSourceConfig(paddle_api_key="key"), team_id=1)

    @mock.patch(PADDLE_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert self._validate() == (True, None)

    @pytest.mark.parametrize(
        "status_code,expected",
        [(401, INVALID_API_KEY_ERROR), (403, MISSING_PERMISSIONS_ERROR)],
    )
    @mock.patch(PADDLE_SESSION_PATCH)
    def test_refusal_message(self, mock_session, status_code: int, expected: str) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        valid, message = self._validate()

        assert valid is False
        assert message == expected
        # The wizard shows this string and nothing else, so it has to name a next step and must
        # not carry the probed endpoint name the permission error reports.
        assert "reconnect" in message
        assert "Missing permissions" not in message

    @mock.patch(PADDLE_SESSION_PATCH)
    def test_unreachable_paddle_does_not_blame_the_key(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        valid, message = self._validate()

        # Paddle never judged the key, so telling the customer to replace it would send them
        # rotating a key that works.
        assert valid is False
        assert message == KEY_CHECK_FAILED_ERROR

    @mock.patch(f"{SOURCE_MODULE}.validate_paddle_credentials", side_effect=RuntimeError("probe blew up"))
    @mock.patch(f"{SOURCE_MODULE}.capture_exception")
    def test_unexpected_failure_is_captured_not_shown(self, mock_capture, _mock_validate) -> None:
        valid, message = self._validate()

        assert valid is False
        assert message == KEY_CHECK_FAILED_ERROR
        assert "probe blew up" not in message
        assert mock_capture.call_count == 1


class TestFormatDatetimeQueryValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            # Paddle's billed_at[GT] filter is UTC-only, so an offset timestamp must be normalized.
            ("2024-01-01T02:00:00+02:00", "2024-01-01T00:00:00Z"),
            (datetime(2024, 1, 1, 0, 0, 0), "2024-01-01T00:00:00Z"),
        ],
    )
    def test_normalizes_to_utc_z(self, value: Any, expected: str) -> None:
        assert _format_paddle_datetime_query_value(value) == expected
