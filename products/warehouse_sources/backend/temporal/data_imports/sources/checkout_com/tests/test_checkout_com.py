import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    PAGE_SIZE,
    CheckoutComResumeConfig,
    _format_timestamp,
    _hosts,
    checkout_com_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# OAuth2Auth mints tokens through its own tracked session in the auth module.
AUTH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
)
# validate_credentials probes through a tracked session built in the checkout_com module.
PROBE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com.make_tracked_session"
)


def _disputes_response(items: list[dict[str, Any]], total: int | None = None, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"limit": PAGE_SIZE, "total_count": total if total is not None else len(items)}
    if not drop_data:
        body["data"] = items
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _token_response(expires_in: int = 3600) -> mock.MagicMock:
    # OAuth2Auth reads the token exchange body via response.raw.read (stream=True).
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.raw.read.return_value = json.dumps({"access_token": "the-token", "expires_in": expires_in}).encode()
    return resp


def _make_manager(resume_state: CheckoutComResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock RESTClient session and snapshot each request AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead. A real
    ``requests.Session`` does the preparing so the auth (OAuth2 token mint + Bearer header) is
    actually applied, letting tests assert on the minted Authorization header and the token host.
    """
    session.headers = {}
    real_session = requests.Session()
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        prepared = real_session.prepare_request(request)
        snapshots.append({"params": dict(request.params or {}), "url": prepared.url, "headers": dict(prepared.headers)})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    manager: mock.MagicMock,
    environment: str = "production",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return checkout_com_source(
        environment=environment,
        client_id="ack_id",
        client_secret="secret",
        endpoint="disputes",
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestHosts:
    def test_production_and_sandbox_hosts(self):
        assert _hosts("production")["api"] == "https://api.checkout.com"
        assert _hosts("sandbox")["auth"] == "https://access.sandbox.checkout.com/connect/token"

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _hosts("evil")


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, True),
            # 403 = token minted (keys valid) but missing the disputes scope — accept at create time.
            (403, True),
            (401, False),
        ],
    )
    @mock.patch(PROBE_SESSION_PATCH)
    def test_maps_probe_status(self, mock_session, status, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("production", "ack_id", "secret") is expected

    @mock.patch(PROBE_SESSION_PATCH)
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("production", "ack_id", "secret") is False

    def test_invalid_environment(self):
        assert validate_credentials("evil", "ack_id", "secret") is False


class TestPagination:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_skip_until_total(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        MockAuthSession.return_value.post.return_value = _token_response()
        full_page = [{"id": f"dsp_{i}"} for i in range(PAGE_SIZE)]
        snapshots = _wire(
            session,
            [
                _disputes_response(full_page, total=PAGE_SIZE + 1),
                _disputes_response([{"id": "dsp_last"}], total=PAGE_SIZE + 1),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == [*(f"dsp_{i}" for i in range(PAGE_SIZE)), "dsp_last"]
        assert snapshots[0]["params"]["skip"] == 0
        assert snapshots[0]["params"]["limit"] == PAGE_SIZE
        assert snapshots[1]["params"]["skip"] == PAGE_SIZE
        # Checkpoint saved after the first page (points at the next page); the final page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CheckoutComResumeConfig(skip=PAGE_SIZE)

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_total_count_without_saving(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        MockAuthSession.return_value.post.return_value = _token_response()
        full_page = [{"id": f"dsp_{i}"} for i in range(PAGE_SIZE)]
        _wire(session, [_disputes_response(full_page, total=PAGE_SIZE)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_skip(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        MockAuthSession.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_disputes_response([{"id": "dsp_501"}])])

        manager = _make_manager(CheckoutComResumeConfig(skip=500))
        _rows(_source(manager))

        assert snapshots[0]["params"]["skip"] == 500

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        MockAuthSession.return_value.post.return_value = _token_response()
        _wire(session, [_disputes_response([], total=0)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_treated_as_end_of_list(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        MockAuthSession.return_value.post.return_value = _token_response()
        _wire(session, [_disputes_response([], total=0, drop_data=True)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1


class TestIncremental:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_from_filter(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        MockAuthSession.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_disputes_response([], total=0)])

        manager = _make_manager()
        _rows(
            _source(
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["from"] == "2024-01-02T00:00:00Z"

    @pytest.mark.parametrize("should_use_incremental_field, last_value", [(False, None), (True, None)])
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_from_filter_without_watermark(
        self, MockSession, MockAuthSession, should_use_incremental_field, last_value
    ) -> None:
        session = MockSession.return_value
        MockAuthSession.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_disputes_response([], total=0)])

        manager = _make_manager()
        _rows(
            _source(
                manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
            )
        )

        assert "from" not in snapshots[0]["params"]


class TestAuth:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mints_token_once_and_sends_bearer(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        auth_session = MockAuthSession.return_value
        auth_session.post.return_value = _token_response()
        full_page = [{"id": f"dsp_{i}"} for i in range(PAGE_SIZE)]
        snapshots = _wire(
            session,
            [
                _disputes_response(full_page, total=PAGE_SIZE + 1),
                _disputes_response([{"id": "dsp_last"}], total=PAGE_SIZE + 1),
            ],
        )

        _rows(_source(_make_manager()))

        # One mint covers the whole run while the token is unexpired.
        assert auth_session.post.call_count == 1
        token_url = auth_session.post.call_args.args[0]
        assert token_url == "https://access.checkout.com/connect/token"
        # Client credentials travel as HTTP Basic; grant is client_credentials.
        assert auth_session.post.call_args.kwargs["auth"] == ("ack_id", "secret")
        assert auth_session.post.call_args.kwargs["data"]["grant_type"] == "client_credentials"
        assert all(s["headers"]["Authorization"] == "Bearer the-token" for s in snapshots)

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_remints_token_when_expired_mid_run(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        auth_session = MockAuthSession.return_value
        # expires_in=0 makes the token expire immediately, forcing a re-mint per request —
        # the deterministic stand-in for a sync outliving the ~1h token lifetime.
        auth_session.post.return_value = _token_response(expires_in=0)
        full_page = [{"id": f"dsp_{i}"} for i in range(PAGE_SIZE)]
        _wire(
            session,
            [
                _disputes_response(full_page, total=PAGE_SIZE + 1),
                _disputes_response([{"id": "dsp_last"}], total=PAGE_SIZE + 1),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert len(rows) == PAGE_SIZE + 1
        assert auth_session.post.call_count == 2

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sandbox_uses_sandbox_hosts(self, MockSession, MockAuthSession) -> None:
        session = MockSession.return_value
        auth_session = MockAuthSession.return_value
        auth_session.post.return_value = _token_response()
        snapshots = _wire(session, [_disputes_response([], total=0)])

        _rows(_source(_make_manager(), environment="sandbox"))

        token_url = auth_session.post.call_args.args[0]
        assert urlparse(token_url).netloc == "access.sandbox.checkout.com"
        assert urlparse(snapshots[0]["url"]).netloc == "api.sandbox.checkout.com"


class TestCheckoutComSourceResponse:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata(self, MockSession, MockAuthSession):
        response = _source(_make_manager())

        assert response.name == "disputes"
        assert response.primary_keys == ["id"]
        # Disputes return newest-first — watermark commits only at run end.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["received_on"]
