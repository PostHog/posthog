import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio import (
    PersonioResumeConfig,
    _format_updated_at,
    personio_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import (
    ENDPOINTS,
    PERSONIO_ENDPOINTS,
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
    resp.url = "https://api.personio.de/v2/persons"
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"_data": items, "_meta": {"links": {}}}
    if next_url:
        body["_meta"]["links"]["next"] = {"href": next_url}
    return body


def _token_response(status_code: int = 200, expires_in: int = 86400) -> mock.MagicMock:
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


def _make_manager(resume_state: PersonioResumeConfig | None = None) -> mock.MagicMock:
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
    return personio_source(
        client_id="cid",
        client_secret="sec",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestFormatUpdatedAt:
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
        assert _format_updated_at(value) == expected


class TestValidateCredentials:
    @mock.patch(AUTH_SESSION_PATCH)
    def test_valid_when_token_mints(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        assert validate_credentials("cid", "sec") is True

    @mock.patch(AUTH_SESSION_PATCH)
    def test_mint_sends_client_credentials_in_body(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        validate_credentials("cid", "sec")

        call = mock_session.return_value.post.call_args
        # Body-mode client auth: credentials ride in the form body, no HTTP Basic auth tuple.
        assert call.args[0] == "https://api.personio.de/v2/auth/token"
        assert call.kwargs["data"] == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": "sec"}
        assert call.kwargs["auth"] is None

    @mock.patch(AUTH_SESSION_PATCH)
    def test_invalid_when_token_mint_rejected(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(status_code=401)
        assert validate_credentials("cid", "sec") is False

    @mock.patch(AUTH_SESSION_PATCH)
    def test_invalid_on_transient_error(self, mock_session):
        mock_session.return_value.post.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("cid", "sec") is False


class TestGetRows:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_meta_next_link(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        next_url = "https://api.personio.de/v2/persons?cursor=cur_abc&limit=50"
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "1"}], next_url=next_url)),
                _response(_page([{"id": "2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("persons", manager))

        assert [row["id"] for row in rows] == ["1", "2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url
        # The self-contained _meta.links.next.href link is followed verbatim on the second request.
        assert snapshots[1]["url"] == next_url

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_carry_bearer_token(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(_source("persons", _make_manager()))

        assert snapshots[0]["headers"]["Authorization"] == "Bearer the-token"

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mints_token_once_across_pages(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(
            session,
            [
                _response(_page([{"id": "1"}], next_url="https://api.personio.de/v2/persons?cursor=p2")),
                _response(_page([{"id": "2"}])),
            ],
        )

        _rows(_source("persons", _make_manager()))

        # One mint covers the whole run while the ~24h token is unexpired.
        assert MockAuth.return_value.post.call_count == 1

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_remints_token_when_expired_mid_run(self, MockSession, MockAuth):
        # expires_in=0 forces a re-mint per request — the deterministic stand-in for a sync
        # outliving the ~24h token lifetime. Replaces the pre-framework reactive-401 re-mint.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response(expires_in=0)
        _wire(
            session,
            [
                _response(_page([{"id": "1"}], next_url="https://api.personio.de/v2/persons?cursor=p2")),
                _response(_page([{"id": "2"}])),
            ],
        )

        rows = _rows(_source("persons", _make_manager()))

        assert [row["id"] for row in rows] == ["1", "2"]
        assert MockAuth.return_value.post.call_count == 2

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_persons_uses_strict_gt_filter(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(
            _source(
                "persons",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["updated_at.gt"] == "2024-01-02T00:00:00Z"
        assert snapshots[0]["params"]["limit"] == 50

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_absence_periods_uses_gte_filter(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(
            _source(
                "absence_periods",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["updated_at.gte"] == "2024-01-02T00:00:00Z"
        assert snapshots[0]["params"]["limit"] == 100

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_has_no_filter(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(_source("persons", _make_manager()))

        assert "updated_at.gt" not in snapshots[0]["params"]
        assert snapshots[0]["params"]["limit"] == 50

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        resume_url = "https://api.personio.de/v2/persons?cursor=cur_resume"
        snapshots = _wire(session, [_response(_page([{"id": "9"}]))])

        manager = _make_manager(PersonioResumeConfig(next_url=resume_url))
        _rows(_source("persons", manager))

        assert snapshots[0]["url"] == resume_url

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_even_with_next_link(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [_response(_page([], next_url="https://api.personio.de/v2/persons?cursor=loop"))])

        manager = _make_manager()
        rows = _rows(_source("persons", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_off_host_next_url(self, MockSession, MockAuth):
        # SSRF guard: a _meta.links.next.href pointing off api.personio.de is rejected before the
        # request (and its bearer token) leaves the process.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [_response(_page([{"id": "1"}], next_url="https://evil.example.com/v2/persons?cursor=x"))])

        with pytest.raises(ValueError):
            _rows(_source("persons", _make_manager()))

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_off_host_resume_url(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [])

        manager = _make_manager(PersonioResumeConfig(next_url="https://evil.example.com/v2/persons"))
        with pytest.raises(ValueError):
            _rows(_source("persons", manager))

        manager.save_state.assert_not_called()


class TestPersonioSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = PERSONIO_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(PERSONIO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
