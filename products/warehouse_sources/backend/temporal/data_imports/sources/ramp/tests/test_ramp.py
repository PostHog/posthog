import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.ramp import (
    PAGE_SIZE,
    RampResumeConfig,
    _base_url,
    _format_timestamp,
    ramp_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.settings import (
    ENDPOINTS,
    RAMP_ENDPOINTS,
    TOKEN_SCOPES,
)

# The RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# OAuth2Auth mints tokens through its own tracked session in the auth module.
AUTH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
)


def _response(payload: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    resp.url = "https://api.ramp.com/developer/v1/test"
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    return {"data": items, "page": {"next": next_url}}


def _token_response(status_code: int = 200, expires_in: int = 864000) -> mock.MagicMock:
    # OAuth2Auth reads the token exchange body via response.raw.read (stream=True).
    resp = mock.MagicMock()
    resp.status_code = status_code
    body: dict[str, Any] = (
        {"access_token": "the-token", "expires_in": expires_in, "token_type": "Bearer"}
        if status_code < 300
        else {"error": "invalid_client"}
    )
    resp.raw.read.return_value = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: RampResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock RESTClient session and snapshot each request AT PREPARE TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead. A real
    ``requests.Session`` does the preparing so the OAuth2 auth (token mint + Bearer header) is
    actually applied, letting tests assert on the minted Authorization header and the request URLs.
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
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return ramp_source(
        environment="production",
        client_id="cid",
        client_secret="sec",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestBaseUrl:
    def test_production_and_sandbox_hosts(self):
        assert _base_url("production") == "https://api.ramp.com"
        assert _base_url("sandbox") == "https://demo-api.ramp.com"

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


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
    @mock.patch(AUTH_SESSION_PATCH)
    def test_valid_when_token_mints(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        assert validate_credentials("production", "cid", "sec") == (True, None)

    @mock.patch(AUTH_SESSION_PATCH)
    def test_mint_requests_documented_scopes(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        validate_credentials("production", "cid", "sec")

        call = mock_session.return_value.post.call_args
        # HTTP Basic client auth: credentials ride in the auth tuple, scopes in the form body.
        assert call.args[0] == "https://api.ramp.com/developer/v1/token"
        assert call.kwargs["data"] == {"grant_type": "client_credentials", "scope": TOKEN_SCOPES}
        assert call.kwargs["auth"] == ("cid", "sec")

    @mock.patch(AUTH_SESSION_PATCH)
    def test_invalid_when_token_mint_rejected(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(status_code=401)

        is_valid, message = validate_credentials("production", "cid", "sec")
        assert is_valid is False
        assert "credentials" in (message or "")

    @mock.patch(AUTH_SESSION_PATCH)
    def test_transient_error_is_not_reported_as_invalid_credentials(self, mock_session):
        mock_session.return_value.post.side_effect = requests.ConnectionError("connection refused")

        is_valid, message = validate_credentials("production", "cid", "sec")
        assert is_valid is False
        assert "Could not reach Ramp" in (message or "")


class TestGetRows:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_page_next_url(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        next_url = "https://api.ramp.com/developer/v1/transactions?start=abc&page_size=100"
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "t1"}], next_url=next_url)),
                _response(_page([{"id": "t2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("transactions", manager))

        assert [row["id"] for row in rows] == ["t1", "t2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url
        # The self-contained page.next link is followed verbatim on the second request.
        assert snapshots[1]["url"] == next_url

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_transactions_use_from_date(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(
            _source(
                "transactions",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["from_date"] == "2024-01-02T00:00:00Z"
        assert snapshots[0]["params"]["page_size"] == PAGE_SIZE

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_has_no_from_date(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(_source("users", _make_manager()))

        assert "/developer/v1/users" in snapshots[0]["url"]
        assert "from_date" not in snapshots[0]["params"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_remints_token_when_expired_mid_run(self, MockSession, MockAuth):
        # expires_in=0 forces a re-mint per request — the deterministic stand-in for a sync
        # outliving the token lifetime. Replaces the pre-framework reactive-401 re-mint.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response(expires_in=0)
        _wire(
            session,
            [
                _response(_page([{"id": "t1"}], next_url="https://api.ramp.com/developer/v1/transactions?p=2")),
                _response(_page([{"id": "t2"}])),
            ],
        )

        rows = _rows(_source("transactions", _make_manager()))

        assert [row["id"] for row in rows] == ["t1", "t2"]
        assert MockAuth.return_value.post.call_count == 2

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mints_token_once_and_sends_bearer(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "t1"}], next_url="https://api.ramp.com/developer/v1/transactions?p=2")),
                _response(_page([{"id": "t2"}])),
            ],
        )

        _rows(_source("transactions", _make_manager()))

        # One mint covers the whole run while the ~10-day token is unexpired.
        assert MockAuth.return_value.post.call_count == 1
        assert all(s["headers"]["Authorization"] == "Bearer the-token" for s in snapshots)

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_url(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        resume_url = "https://api.ramp.com/developer/v1/transactions?start=resume"
        snapshots = _wire(session, [_response(_page([]))])

        manager = _make_manager(RampResumeConfig(next_url=resume_url))
        _rows(_source("transactions", manager))

        assert snapshots[0]["url"] == resume_url

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_next_url_stops(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [_response(_page([], next_url="https://api.ramp.com/developer/v1/transactions?start=loop"))])

        manager = _make_manager()
        rows = _rows(_source("transactions", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_off_host_next_url(self, MockSession, MockAuth):
        # SSRF guard: a page.next pointing off the configured Ramp host is rejected before the
        # request (and its bearer token) leaves the process.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(
            session,
            [_response(_page([{"id": "t1"}], next_url="https://evil.example.com/developer/v1/transactions"))],
        )

        with pytest.raises(ValueError):
            _rows(_source("transactions", _make_manager()))

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_off_host_resume_url(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [])

        manager = _make_manager(RampResumeConfig(next_url="https://evil.example.com/developer/v1/transactions"))
        with pytest.raises(ValueError):
            _rows(_source("transactions", manager))

        manager.save_state.assert_not_called()


class TestRampSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = RAMP_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        # Ordering within incremental windows is undocumented — desc defers the watermark commit
        # to run completion.
        assert response.sort_mode == ("desc" if config.incremental_fields else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    @pytest.mark.parametrize("config", list(RAMP_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "user_transaction_time"
