import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import (
    ENDPOINTS,
    PAGE_SIZE,
    ZUORA_ENDPOINTS,
    ZUORA_ENVIRONMENT_HOSTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.zuora import (
    ZuoraResumeConfig,
    _base_url,
    _format_timestamp,
    validate_credentials,
    zuora_source,
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
    resp.url = "https://rest.zuora.com/object-query/accounts"
    return resp


def _page(items: list[dict[str, Any]], next_page: str | None = None) -> dict[str, Any]:
    return {"data": items, "nextPage": next_page}


def _token_response(status_code: int = 200, expires_in: int = 3599) -> mock.MagicMock:
    # OAuth2Auth reads the token exchange body via response.raw.read (stream=True).
    resp = mock.MagicMock()
    resp.status_code = status_code
    body: dict[str, Any] = (
        {"access_token": "tok-1", "token_type": "bearer", "expires_in": expires_in}
        if status_code < 300
        else {"error": "invalid_client"}
    )
    resp.raw.read.return_value = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ZuoraResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock RESTClient session and snapshot each request AT PREPARE TIME.

    ``request.params`` is mutated across pages, so inspecting it after the run shows only the
    final state — snapshot a copy when each request is prepared instead. A real ``requests.Session``
    does the preparing so the OAuth2 auth (token mint + Bearer header) is actually applied, letting
    tests assert on the minted Authorization header and the request URLs."""
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
    return zuora_source(
        environment="us_production",
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
    @pytest.mark.parametrize("environment, expected", list(ZUORA_ENVIRONMENT_HOSTS.items()))
    def test_environment_hosts(self, environment, expected):
        assert _base_url(environment) == expected

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("nope")


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
    def test_valid_credentials_mint_a_token(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        assert validate_credentials("us_production", "cid", "sec") is True
        call = mock_session.return_value.post.call_args
        # Client credentials ride in the token request form body (body auth method), not HTTP Basic.
        assert call.args[0] == "https://rest.zuora.com/oauth/token"
        assert call.kwargs["data"] == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": "sec"}
        assert call.kwargs["auth"] is None

    @mock.patch(AUTH_SESSION_PATCH)
    def test_invalid_credentials(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(status_code=401)

        assert validate_credentials("us_production", "cid", "bad") is False

    @mock.patch(AUTH_SESSION_PATCH)
    def test_network_error_propagates(self, mock_session):
        # A transient network failure must not be reported as invalid credentials.
        mock_session.return_value.post.side_effect = requests.ConnectionError("boom")

        with pytest.raises(requests.ConnectionError):
            validate_credentials("us_production", "cid", "sec")

    @mock.patch(AUTH_SESSION_PATCH)
    def test_sandbox_environment_uses_sandbox_host(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        validate_credentials("eu_sandbox", "cid", "sec")

        assert mock_session.return_value.post.call_args.args[0] == "https://rest.sandbox.eu.zuora.com/oauth/token"


class TestGetRows:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_with_next_page_cursor(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "a1"}], next_page="cur-1")),
                _response(_page([{"id": "a2"}], next_page=None)),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("accounts", manager))

        assert [row["id"] for row in rows] == ["a1", "a2"]
        first_url = snapshots[0]["url"]
        assert first_url.startswith("https://rest.zuora.com/object-query/accounts?")
        assert "pageSize=99" in first_url
        assert "sort%5B%5D=updateddate.ASC" in first_url
        # The cursor encodes the full query context, so the original params are dropped on page 2.
        assert snapshots[1]["params"] == {"cursor": "cur-1"}
        assert "cursor=cur-1" in snapshots[1]["url"]
        assert "pageSize" not in snapshots[1]["url"]
        assert "sort%5B%5D" not in snapshots[1]["url"]
        # A save happens once — after page 1, whose nextPage still points at more data.
        assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["cur-1"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_passes_updateddate_gt_filter(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([], next_page=None))])

        _rows(
            _source(
                "invoices",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["filter[]"] == "updateddate.GT:2024-01-02T03:04:05Z"
        assert "filter%5B%5D=updateddate.GT%3A2024-01-02T03%3A04%3A05Z" in snapshots[0]["url"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_has_no_filter(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([], next_page=None))])

        _rows(_source("accounts", _make_manager()))

        assert "filter[]" not in snapshots[0]["params"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([{"id": "a9"}], next_page=None))])

        manager = _make_manager(ZuoraResumeConfig(cursor="cur-9"))
        _rows(_source("accounts", manager))

        # The resumed run targets the saved page with the cursor alone.
        assert snapshots[0]["params"] == {"cursor": "cur-9"}
        assert "cursor=cur-9" in snapshots[0]["url"]
        assert "pageSize" not in snapshots[0]["url"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_remints_token_when_expired_mid_run(self, MockSession, MockAuth):
        # expires_in=0 forces a re-mint per request — the deterministic stand-in for a sync
        # outliving the ~1h token lifetime. Replaces the pre-framework reactive-401 re-mint.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response(expires_in=0)
        _wire(
            session,
            [
                _response(_page([{"id": "a1"}], next_page="cur-1")),
                _response(_page([{"id": "a2"}], next_page=None)),
            ],
        )

        rows = _rows(_source("accounts", _make_manager()))

        assert [row["id"] for row in rows] == ["a1", "a2"]
        assert MockAuth.return_value.post.call_count == 2

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mints_token_once_and_sends_bearer(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "a1"}], next_page="cur-1")),
                _response(_page([{"id": "a2"}], next_page=None)),
            ],
        )

        _rows(_source("accounts", _make_manager()))

        # One mint covers the whole run while the ~1h token is unexpired.
        assert MockAuth.return_value.post.call_count == 1
        assert all(s["headers"]["Authorization"] == "Bearer tok-1" for s in snapshots)

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hyphenated_object_paths(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([], next_page=None))])

        _rows(_source("credit_memos", _make_manager()))

        assert "/object-query/credit-memos?" in snapshots[0]["url"]


class TestZuoraSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Pages are requested sorted ascending by updateddate.
        assert response.sort_mode == "asc"

    def test_all_endpoints_have_paths(self):
        assert set(ENDPOINTS) == set(ZUORA_ENDPOINTS.keys())

    def test_page_size_cap(self):
        assert PAGE_SIZE == 99
