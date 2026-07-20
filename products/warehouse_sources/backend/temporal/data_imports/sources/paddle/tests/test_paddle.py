import json
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response
from requests.adapters import HTTPAdapter

from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PADDLE_BASE_URL,
    PaddlePermissionError,
    PaddleResumeConfig,
    _get_paddle_session,
    paddle_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the paddle module.
PADDLE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, *, next_url: str | None = None, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"meta": {"pagination": {"per_page": 200, "next": next_url}}}
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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_makes_one_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}], next_url=None)])

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True)])

        # Paddle treats a body without "data" leniently (0 rows), not as a hard error.
        manager = _make_manager()
        rows = _rows(_source("customers", manager))
        assert rows == []


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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_without_incremental_flag(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": "t_1"}], next_url=None)])

        manager = _make_manager()
        _rows(
            _source("transactions", manager, should_use_incremental_field=False, db_incremental_field_last_value=None)
        )

        # order_by still points at the incremental field, but no watermark filter is applied.
        assert params[0]["order_by"] == "billed_at[ASC]"
        assert "billed_at[GT]" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_without_last_value(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": "t_1"}], next_url=None)])

        manager = _make_manager()
        _rows(_source("transactions", manager, should_use_incremental_field=True, db_incremental_field_last_value=None))

        assert "billed_at[GT]" not in params[0]


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_url_then_empties_on_completion(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{PADDLE_BASE_URL}/customers?after=c_1"
        _wire(session, [_response([{"id": "c_1"}], next_url=next_url), _response([{"id": "c_2"}], next_url=None)])

        manager = _make_manager()
        _rows(_source("customers", manager))

        # Saved after each page: the next-page URL while pages remain, then an empty marker at the end.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [PaddleResumeConfig(next_url=next_url), PaddleResumeConfig(next_url="")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        saved_url = f"{PADDLE_BASE_URL}/customers?after=saved"
        params, urls = _wire(session, [_response([{"id": "c_9"}], next_url=None)])

        manager = _make_manager(PaddleResumeConfig(next_url=saved_url))
        rows = _rows(_source("customers", manager))

        assert [r["id"] for r in rows] == ["c_9"]
        # A resumed run starts at the saved next-page URL with no re-appended list params.
        assert urls[0] == saved_url
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_saved_url_starts_fresh(self, MockSession) -> None:
        session = MockSession.return_value
        params, urls = _wire(session, [_response([{"id": "c_1"}], next_url=None)])

        manager = _make_manager(PaddleResumeConfig(next_url=""))
        _rows(_source("customers", manager))

        # An empty saved marker means the previous sync finished — start from the base path again.
        assert urls[0] == f"{PADDLE_BASE_URL}/customers"
        assert params[0]["per_page"] == 200


class TestValidateCredentials:
    @mock.patch(PADDLE_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key") is True

    @mock.patch(PADDLE_SESSION_PATCH)
    def test_single_table_probes_one_endpoint(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key", "customers") is True
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(PADDLE_SESSION_PATCH)
    def test_permission_error_on_403(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=403)
        with pytest.raises(PaddlePermissionError, match="Missing permissions for"):
            validate_credentials("key")

    @mock.patch(PADDLE_SESSION_PATCH)
    def test_unauthorized_returns_false(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key") is False

    @mock.patch(PADDLE_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestPaddleSession:
    def test_session_retries_rate_limits(self):
        session = _get_paddle_session("pdl_test_key")
        retry = cast(HTTPAdapter, session.get_adapter(PADDLE_BASE_URL)).max_retries

        # A transient 429 must back off and retry rather than failing the whole sync.
        assert retry.total is not None and retry.total > 0
        assert retry.is_retry("GET", 429) is True
        assert retry.respect_retry_after_header is True
        # Persistent failures still surface via response.raise_for_status(), not MaxRetryError.
        assert retry.raise_on_status is False

    def test_auth_failures_are_not_retried(self):
        session = _get_paddle_session("pdl_test_key")
        retry = cast(HTTPAdapter, session.get_adapter(PADDLE_BASE_URL)).max_retries

        # 401/403/400 are credential/config problems handled by get_non_retryable_errors;
        # retrying them would only delay surfacing the error to the user.
        assert retry.is_retry("GET", 401) is False
        assert retry.is_retry("GET", 403) is False
        assert retry.is_retry("GET", 400) is False
