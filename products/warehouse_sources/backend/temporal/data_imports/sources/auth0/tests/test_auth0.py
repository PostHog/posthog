import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.auth0 import auth0 as auth0_module
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.auth0 import (
    Auth0HostNotAllowedError,
    Auth0PaginationLimitError,
    Auth0PaginationStalledError,
    Auth0ResponseTooLargeError,
    Auth0ResumeConfig,
    Auth0RetryableError,
    Auth0TokenManager,
    _build_params,
    _build_url,
    _format_window_value,
    _max_window_value,
    auth0_source,
    get_rows,
    management_audience,
    normalize_domain,
    resolve_window_field,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.settings import AUTH0_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

DOMAIN = "tenant.us.auth0.com"
TOKEN_JSON = {"access_token": "tok", "expires_in": 86400, "token_type": "Bearer"}


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    body = json.dumps(json_data).encode() if json_data is not None else text.encode()
    # Bodies are read via stream=True + iter_content, so serve them in that shape. A fresh
    # iterator per call lets one mock response stand in for repeated reads.
    response.iter_content.side_effect = lambda *args, **kwargs: iter([body] if body else [])
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: for url: https://{DOMAIN}", response=response
        )
    return response


def _token_session() -> mock.MagicMock:
    session = mock.MagicMock()
    session.post.return_value = _response(json_data=TOKEN_JSON)
    return session


def _data_session(get_responses: list[Any]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = get_responses
    return session


def _requested_params(session: mock.MagicMock, index: int) -> dict[str, list[str]]:
    return parse_qs(urlsplit(session.get.call_args_list[index].args[0]).query)


def _user_rows(count: int, updated_at: str, start: int = 0) -> list[dict[str, Any]]:
    return [{"user_id": f"auth0|{start + i}", "updated_at": updated_at} for i in range(count)]


class FakeResumeManager(ResumableSourceManager[Auth0ResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: Optional[Auth0ResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[Auth0ResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[Auth0ResumeConfig]:
        return self.state

    def save_state(self, data: Auth0ResumeConfig) -> None:
        self.saved.append(data)


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("tenant.us.auth0.com", "tenant.us.auth0.com"),
            ("https://tenant.us.auth0.com", "tenant.us.auth0.com"),
            ("http://tenant.us.auth0.com/", "tenant.us.auth0.com"),
            ("  tenant.us.auth0.com  ", "tenant.us.auth0.com"),
            ("tenant.us.auth0.com/api/v2", "tenant.us.auth0.com"),
            ("https://tenant.eu.auth0.com/api/v2/users", "tenant.eu.auth0.com"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_domain(raw) == expected

    def test_audience_is_the_management_api_identifier(self) -> None:
        assert management_audience("https://tenant.us.auth0.com/", "v2") == "https://tenant.us.auth0.com/api/v2/"


class TestFormatWindowValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_window_value(value) == expected

    def test_double_quotes_cannot_escape_the_lucene_term(self) -> None:
        assert _format_window_value('2026-01-01" TO *] OR user_id:*') == "2026-01-01 TO *] OR user_id:*"


class TestResolveWindowField:
    @pytest.mark.parametrize(
        "endpoint, should_use_incremental_field, incremental_field, expected",
        [
            ("users", True, "updated_at", "updated_at"),
            ("users", True, "created_at", "created_at"),
            # An unadvertised cursor never reaches the query string; fall back to the default.
            ("users", True, "last_login", "updated_at"),
            ("users", True, None, "updated_at"),
            # Full refresh sorts on the immutable column so page boundaries stay stable.
            ("users", False, None, "created_at"),
            ("logs", True, "date", "date"),
            ("logs", False, None, "date"),
            ("clients", True, "created_at", None),
            ("log_streams", False, None, None),
        ],
    )
    def test_resolve(
        self,
        endpoint: str,
        should_use_incremental_field: bool,
        incremental_field: Optional[str],
        expected: Optional[str],
    ) -> None:
        resolved = resolve_window_field(AUTH0_ENDPOINTS[endpoint], should_use_incremental_field, incremental_field)
        assert resolved == expected


class TestBuildParams:
    def test_users_incremental_window_filters_and_sorts_ascending(self) -> None:
        params = _build_params(AUTH0_ENDPOINTS["users"], page=0, window_field="updated_at", window_start="2024-01-01")
        assert params["q"] == 'updated_at:["2024-01-01" TO *]'
        assert params["sort"] == "updated_at:1"
        assert params["include_totals"] == "true"
        assert params["search_engine"] == "v3"
        assert params["per_page"] == 100

    def test_first_window_sorts_but_does_not_filter(self) -> None:
        params = _build_params(AUTH0_ENDPOINTS["users"], page=3, window_field="updated_at", window_start=None)
        assert "q" not in params
        assert params["sort"] == "updated_at:1"
        assert params["page"] == 3

    @pytest.mark.parametrize("endpoint", ["clients", "connections", "roles", "organizations", "resource_servers"])
    def test_plain_collections_send_no_search_params(self, endpoint: str) -> None:
        params = _build_params(AUTH0_ENDPOINTS[endpoint], page=0, window_field=None, window_start=None)
        assert "q" not in params
        assert "sort" not in params
        assert "search_engine" not in params
        assert params["include_totals"] == "true"

    def test_actions_omits_include_totals(self) -> None:
        # The Actions API returns its own totals envelope and does not document include_totals.
        params = _build_params(AUTH0_ENDPOINTS["actions"], page=0, window_field=None, window_start=None)
        assert "include_totals" not in params
        assert params["page"] == 0

    def test_unpaginated_endpoint_sends_no_params(self) -> None:
        assert _build_params(AUTH0_ENDPOINTS["log_streams"], page=0, window_field=None, window_start=None) == {}

    def test_build_url_applies_the_resolved_api_version(self) -> None:
        url = _build_url(DOMAIN, AUTH0_ENDPOINTS["actions"], "v2", {})
        assert url == f"https://{DOMAIN}/api/v2/actions/actions"


class TestMaxWindowValue:
    def test_takes_the_maximum_not_the_last_row(self) -> None:
        rows = [{"updated_at": "2024-01-02T00:00:00.000Z"}, {"updated_at": "2024-01-01T00:00:00.000Z"}]
        assert _max_window_value(rows, "updated_at") == "2024-01-02T00:00:00.000Z"

    @pytest.mark.parametrize("rows", [[], [{"updated_at": None}], [{"user_id": "auth0|1"}]])
    def test_missing_values_yield_none(self, rows: list[dict[str, Any]]) -> None:
        assert _max_window_value(rows, "updated_at") is None


class TestTokenManager:
    def test_mints_once_and_caches(self) -> None:
        session = _token_session()
        manager = Auth0TokenManager(session, DOMAIN, "cid", "secret", "v2")

        assert manager.get_token() == "tok"
        assert manager.get_token() == "tok"
        assert session.post.call_count == 1

        body = session.post.call_args.kwargs["json"]
        assert body["grant_type"] == "client_credentials"
        assert body["audience"] == f"https://{DOMAIN}/api/v2/"
        assert session.post.call_args.kwargs["allow_redirects"] is False

    def test_re_mints_once_the_token_expires(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            _response(json_data={"access_token": "first", "expires_in": 1}),
            _response(json_data={"access_token": "second", "expires_in": 86400}),
        ]
        manager = Auth0TokenManager(session, DOMAIN, "cid", "secret", "v2")

        assert manager.get_token() == "first"
        # A 1s lifetime is already inside the refresh margin, so the next call re-mints.
        assert manager.get_token() == "second"
        assert session.post.call_count == 2

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_transient_token_failures_are_retryable(self, status_code: int) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=status_code)
        manager = Auth0TokenManager(session, DOMAIN, "cid", "secret", "v2")

        with pytest.raises(Auth0RetryableError):
            manager.get_token()

    def test_redirected_token_endpoint_is_refused(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=302)
        manager = Auth0TokenManager(session, DOMAIN, "cid", "secret", "v2")

        with pytest.raises(Auth0HostNotAllowedError):
            manager.get_token()

    def test_oversized_token_body_is_refused(self) -> None:
        session = mock.MagicMock()
        response = _response(json_data=TOKEN_JSON)
        response.iter_content.side_effect = lambda *args, **kwargs: iter([b"x" * 1024])
        session.post.return_value = response
        manager = Auth0TokenManager(session, DOMAIN, "cid", "secret", "v2")

        with mock.patch.object(auth0_module, "MAX_RESPONSE_BYTES", 16):
            with pytest.raises(Auth0ResponseTooLargeError):
                manager.get_token()


class TestGetRows:
    def _run(
        self,
        endpoint: str,
        get_responses: list[Any],
        manager: Optional[FakeResumeManager] = None,
        **kwargs: Any,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock, FakeResumeManager]:
        manager = manager or FakeResumeManager()
        data_session = _data_session(get_responses)
        with (
            mock.patch.object(auth0_module, "_is_host_safe", return_value=(True, None)),
            mock.patch.object(auth0_module, "make_tracked_session", side_effect=[_token_session(), data_session]),
        ):
            batches = list(
                get_rows(
                    domain=DOMAIN,
                    client_id="cid",
                    client_secret="secret",
                    endpoint=endpoint,
                    api_version="v2",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                    **kwargs,
                )
            )
        return batches, data_session, manager

    def test_unpaginated_endpoint_yields_the_bare_array_once(self) -> None:
        rows = [{"id": "lst_1", "type": "http"}]
        batches, session, manager = self._run("log_streams", [_response(json_data=rows)])

        assert batches == [rows]
        assert session.get.call_count == 1
        assert manager.saved == []

    def test_pagination_stops_once_total_is_reached(self) -> None:
        page_0 = {"clients": [{"client_id": str(i)} for i in range(100)], "total": 150}
        page_1 = {"clients": [{"client_id": str(i)} for i in range(100, 150)], "total": 150}
        batches, session, manager = self._run("clients", [_response(json_data=page_0), _response(json_data=page_1)])

        assert [len(batch) for batch in batches] == [100, 50]
        assert session.get.call_count == 2
        assert manager.saved == [Auth0ResumeConfig(page=1, window_start=None)]

    def test_pagination_stops_on_a_short_page_without_totals(self) -> None:
        page = {"actions": [{"id": "a1"}]}
        batches, session, _ = self._run("actions", [_response(json_data=page)])

        assert batches == [[{"id": "a1"}]]
        assert session.get.call_count == 1

    def test_pagination_stops_on_an_empty_page(self) -> None:
        batches, session, _ = self._run("roles", [_response(json_data={"roles": [], "total": 0})])

        assert batches == []
        assert session.get.call_count == 1

    def test_incremental_run_seeds_the_window_from_the_watermark(self) -> None:
        page = {"users": _user_rows(1, "2024-05-01T00:00:00.000Z"), "total": 1}
        _, session, _ = self._run(
            "users",
            [_response(json_data=page)],
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2024, 4, 1, tzinfo=UTC),
        )

        params = _requested_params(session, 0)
        assert params["q"] == ['updated_at:["2024-04-01T00:00:00.000Z" TO *]']
        assert params["sort"] == ["updated_at:1"]

    def test_window_slides_past_the_search_result_cap(self) -> None:
        newest = "2024-06-02T00:00:00.000Z"
        page_0 = {"users": _user_rows(100, "2024-06-01T00:00:00.000Z"), "total": 5000}
        page_1 = {"users": _user_rows(100, newest, start=100), "total": 5000}
        page_2 = {"users": _user_rows(3, newest, start=200), "total": 3}

        with mock.patch.object(auth0_module, "SEARCH_RESULT_CAP", 200):
            batches, session, manager = self._run(
                "users",
                [_response(json_data=page_0), _response(json_data=page_1), _response(json_data=page_2)],
                should_use_incremental_field=True,
                incremental_field="updated_at",
            )

        assert [len(batch) for batch in batches] == [100, 100, 3]
        # The third request restarts at page 0 with the window's lower bound moved to the newest
        # row seen — that is how the collection is walked past Auth0's 1000-result ceiling.
        third = _requested_params(session, 2)
        assert third["page"] == ["0"]
        assert third["q"] == [f'updated_at:["{newest}" TO *]']
        assert manager.saved == [
            Auth0ResumeConfig(page=1, window_start=None),
            Auth0ResumeConfig(page=0, window_start=newest),
        ]

    def test_window_that_cannot_advance_fails_loudly(self) -> None:
        stuck = "2024-06-01T00:00:00.000Z"
        page = {"users": _user_rows(100, stuck), "total": 5000}

        with mock.patch.object(auth0_module, "SEARCH_RESULT_CAP", 200):
            with pytest.raises(Auth0PaginationStalledError):
                self._run(
                    "users",
                    [_response(json_data=page), _response(json_data=page)],
                    should_use_incremental_field=True,
                    incremental_field="updated_at",
                    db_incremental_field_last_value=stuck,
                )

    def test_non_windowed_collection_never_slides(self) -> None:
        page_0 = {"clients": [{"client_id": str(i)} for i in range(100)], "total": 250}
        page_1 = {"clients": [{"client_id": str(i)} for i in range(100, 200)], "total": 250}
        page_2 = {"clients": [{"client_id": str(i)} for i in range(200, 250)], "total": 250}

        with mock.patch.object(auth0_module, "SEARCH_RESULT_CAP", 100):
            _, session, manager = self._run(
                "clients",
                [_response(json_data=page_0), _response(json_data=page_1), _response(json_data=page_2)],
            )

        assert [_requested_params(session, i)["page"] for i in range(3)] == [["0"], ["1"], ["2"]]
        assert all(state.window_start is None for state in manager.saved)

    def test_resumes_from_saved_page_and_window(self) -> None:
        resumed_window = "2024-07-01T00:00:00.000Z"
        page = {"users": _user_rows(1, "2024-07-02T00:00:00.000Z"), "total": 1}
        _, session, _ = self._run(
            "users",
            [_response(json_data=page)],
            manager=FakeResumeManager(Auth0ResumeConfig(page=4, window_start=resumed_window)),
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="2020-01-01T00:00:00.000Z",
        )

        params = _requested_params(session, 0)
        # The saved window wins over the (older) database watermark.
        assert params["page"] == ["4"]
        assert params["q"] == [f'updated_at:["{resumed_window}" TO *]']

    def test_runaway_pagination_is_bounded(self) -> None:
        page = {"clients": [{"client_id": str(i)} for i in range(100)], "total": 10**9}

        with mock.patch.object(auth0_module, "MAX_PAGES", 2):
            with pytest.raises(Auth0PaginationLimitError):
                self._run("clients", [_response(json_data=page)] * 3)

    def test_redirected_data_request_is_refused(self) -> None:
        with pytest.raises(Auth0HostNotAllowedError):
            self._run("roles", [_response(status_code=302)])

    def test_internal_domain_is_blocked_before_any_request(self) -> None:
        manager = FakeResumeManager()
        with mock.patch.object(auth0_module, "_is_host_safe", return_value=(False, "resolves to a private address")):
            with pytest.raises(Auth0HostNotAllowedError):
                list(
                    get_rows(
                        domain="internal.auth0.com",
                        client_id="cid",
                        client_secret="secret",
                        endpoint="roles",
                        api_version="v2",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_propagate(self, status_code: int) -> None:
        with pytest.raises(requests.HTTPError):
            self._run("roles", [_response(status_code=status_code)])


class TestValidateCredentials:
    def _validate(
        self,
        *,
        post_response: Any,
        get_response: Any = None,
        schema_name: Optional[str] = None,
        domain: str = DOMAIN,
        host_safe: bool = True,
    ) -> tuple[bool, str | None]:
        session = mock.MagicMock()
        session.post.return_value = post_response
        if get_response is not None:
            session.get.return_value = get_response
        with (
            mock.patch.object(
                auth0_module, "_is_host_safe", return_value=(host_safe, None if host_safe else "private address")
            ),
            mock.patch.object(auth0_module, "make_tracked_session", return_value=session),
        ):
            return validate_credentials(domain, "cid", "secret", "v2", schema_name=schema_name, team_id=1)

    def test_token_exchange_alone_is_enough_at_source_create(self) -> None:
        assert self._validate(post_response=_response(json_data=TOKEN_JSON)) == (True, None)

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_bad_client_credentials_are_rejected(self, status_code: int) -> None:
        ok, error = self._validate(post_response=_response(status_code=status_code))
        assert ok is False
        assert error == "Invalid Auth0 client ID or client secret"

    @pytest.mark.parametrize("domain", ["", "   ", "https://", "tenant us auth0 com", "tenant.auth0.com:8080"])
    def test_malformed_domains_are_rejected(self, domain: str) -> None:
        assert self._validate(post_response=_response(json_data=TOKEN_JSON), domain=domain) == (
            False,
            "Invalid Auth0 domain",
        )

    def test_internal_domain_is_rejected(self) -> None:
        ok, error = self._validate(post_response=_response(json_data=TOKEN_JSON), host_safe=False)
        assert ok is False
        assert error == "private address"

    def test_scoped_probe_accepts_a_reachable_collection(self) -> None:
        result = self._validate(
            post_response=_response(json_data=TOKEN_JSON),
            get_response=_response(json_data={"users": [], "total": 0}),
            schema_name="users",
        )
        assert result == (True, None)

    @pytest.mark.parametrize(
        "endpoint, scope",
        [("users", "read:users"), ("logs", "read:logs"), ("log_streams", "read:log_streams")],
    )
    def test_scoped_probe_names_the_missing_scope(self, endpoint: str, scope: str) -> None:
        ok, error = self._validate(
            post_response=_response(json_data=TOKEN_JSON),
            get_response=_response(status_code=403),
            schema_name=endpoint,
        )
        assert ok is False
        assert error is not None
        assert scope in error

    def test_scoped_probe_refuses_a_redirect(self) -> None:
        ok, error = self._validate(
            post_response=_response(json_data=TOKEN_JSON),
            get_response=_response(status_code=302),
            schema_name="roles",
        )
        assert (ok, error) == (False, auth0_module.HOST_NOT_ALLOWED_ERROR)

    def test_network_failure_surfaces_rather_than_passing(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError("no route to host")
        with (
            mock.patch.object(auth0_module, "_is_host_safe", return_value=(True, None)),
            mock.patch.object(auth0_module, "make_tracked_session", return_value=session),
        ):
            ok, error = validate_credentials(DOMAIN, "cid", "secret", "v2", team_id=1)
        assert ok is False
        assert error is not None


class TestAuth0Source:
    @pytest.mark.parametrize(
        "endpoint, primary_key, partition_key",
        [
            ("users", "user_id", "created_at"),
            ("logs", "log_id", "date"),
            ("clients", "client_id", None),
            ("connections", "id", None),
            ("log_streams", "id", None),
        ],
    )
    def test_response_shape_per_endpoint(self, endpoint: str, primary_key: str, partition_key: Optional[str]) -> None:
        response = auth0_source(
            domain=DOMAIN,
            client_id="cid",
            client_secret="secret",
            endpoint=endpoint,
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
            team_id=1,
        )

        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)

    def test_items_is_lazy(self) -> None:
        response = auth0_source(
            domain=DOMAIN,
            client_id="cid",
            client_secret="secret",
            endpoint="roles",
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
            team_id=1,
        )

        # Building the response must not touch the network; only iterating does.
        with mock.patch.object(auth0_module, "_is_host_safe", return_value=(True, None)):
            with mock.patch.object(
                auth0_module,
                "make_tracked_session",
                side_effect=[_token_session(), _data_session([_response(json_data={"roles": [], "total": 0})])],
            ):
                assert list(cast("Iterable[Any]", response.items())) == []
