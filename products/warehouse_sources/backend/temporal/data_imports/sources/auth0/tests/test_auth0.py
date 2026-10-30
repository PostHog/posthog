import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.auth0 import auth0 as auth0_module
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.auth0 import (
    Auth0HostNotAllowedError,
    Auth0PaginationLimitError,
    Auth0PaginationStalledError,
    Auth0ResponseTooLargeError,
    Auth0ResponseTooSlowError,
    Auth0ResumeConfig,
    Auth0RetryableError,
    Auth0TokenManager,
    _build_params,
    _format_window_value,
    _reject_redirect_response,
    resolve_window_field,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.settings import AUTH0_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.source import Auth0Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.auth0 import Auth0SourceConfig

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


def _user_rows(count: int, updated_at: str, start: int = 0) -> list[dict[str, Any]]:
    return [{"user_id": f"auth0|{start + i}", "updated_at": updated_at} for i in range(count)]


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
    def test_unpaginated_endpoint_sends_no_params(self) -> None:
        assert _build_params(AUTH0_ENDPOINTS["log_streams"], page=0, window_field=None, window_start=None) == {}


class TestTokenManager:
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

    def test_download_deadline_closes_a_blocked_response(self) -> None:
        class ImmediateTimer:
            daemon = False

            def __init__(self, interval: float, callback: Any) -> None:
                self.callback = callback

            def start(self) -> None:
                self.callback()

            def cancel(self) -> None:
                pass

        session = _token_session()
        manager = Auth0TokenManager(session, DOMAIN, "cid", "secret", "v2")

        with mock.patch.object(auth0_module.threading, "Timer", ImmediateTimer):
            with pytest.raises(Auth0ResponseTooSlowError):
                manager.get_token()

        session.post.return_value.close.assert_called()

    def test_redirect_hook_closes_before_raising(self) -> None:
        response = _response(status_code=302)

        with pytest.raises(Auth0HostNotAllowedError):
            _reject_redirect_response(response)

        response.close.assert_called_once()


class TestGetRows:
    def _run(
        self,
        endpoint: str,
        get_responses: list[ScriptedResponse],
        resume_state: Auth0ResumeConfig | None = None,
        domain: str = DOMAIN,
        **kwargs: Any,
    ) -> DriveResult:
        driver = SourceDriver(
            Auth0Source(), Auth0SourceConfig(auth0_domain=domain, client_id="cid", client_secret="secret")
        )
        return driver.run(
            endpoint,
            [ScriptedResponse(json=TOKEN_JSON), *get_responses],
            resume_state=resume_state,
            **kwargs,
        )

    def test_log_streams_omit_sink_credentials(self) -> None:
        rows = [
            {
                "id": "lst_1",
                "type": "http",
                "sink": {
                    "httpEndpoint": "https://example.com/logs",
                    "httpAuthorization": "Bearer secret",
                    "httpCustomHeaders": [{"header": "X-Api-Key", "value": "secret"}],
                },
            }
        ]
        result = self._run("log_streams", [ScriptedResponse(json=rows)])

        assert result.raised is None
        assert result.items == [[{"id": "lst_1", "type": "http"}]]
        assert result.paths == ["/oauth/token", "/api/v2/log-streams"]
        assert result.saved_states == []

        redirect_result = self._run(
            "log_streams", [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/"})]
        )
        assert isinstance(redirect_result.raised, Auth0HostNotAllowedError)

    def test_resource_servers_omit_signing_secret(self) -> None:
        page = {"resource_servers": [{"id": "rs_1", "identifier": "https://api.example.com", "signing_secret": "shh"}]}
        result = self._run("resource_servers", [ScriptedResponse(json=page)])

        assert result.raised is None
        assert result.items == [[{"id": "rs_1", "identifier": "https://api.example.com"}]]

    def test_users_omit_identity_provider_tokens(self) -> None:
        page = {
            "users": [
                {
                    "user_id": "auth0|1",
                    "email": "a@example.com",
                    "identities": [
                        {
                            "connection": "google-oauth2",
                            "provider": "google-oauth2",
                            "user_id": "123",
                            "access_token": "shh-access",
                            "access_token_secret": "shh-access-secret",
                            "refresh_token": "shh-refresh",
                        }
                    ],
                }
            ],
            "total": 1,
        }
        result = self._run("users", [ScriptedResponse(json=page)])

        assert result.raised is None
        assert result.items == [
            [
                {
                    "user_id": "auth0|1",
                    "email": "a@example.com",
                    "identities": [
                        {
                            "connection": "google-oauth2",
                            "provider": "google-oauth2",
                            "user_id": "123",
                        }
                    ],
                }
            ]
        ]

    def test_window_slides_past_the_search_result_cap(self) -> None:
        newest = "2024-06-02T00:00:00.000Z"
        page_0 = {"users": _user_rows(100, "2024-06-01T00:00:00.000Z"), "total": 200}
        page_1 = {
            "users": _user_rows(50, "2024-06-01T00:00:00.000Z", start=100) + _user_rows(50, newest, start=150),
            "total": 200,
        }
        # The inclusive lower bound re-reads 49 users already synced at `newest`. `auth0|150` comes
        # back too, updated after the slide, so its newer version must not be dropped.
        updated = {"user_id": "auth0|150", "updated_at": "2024-06-03T00:00:00.000Z"}
        page_2 = {"users": [*_user_rows(52, newest, start=151), updated], "total": 53}

        with mock.patch.object(auth0_module, "SEARCH_RESULT_CAP", 200):
            result = self._run(
                "users",
                [ScriptedResponse(json=page_0), ScriptedResponse(json=page_1), ScriptedResponse(json=page_2)],
                incremental_field="updated_at",
            )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [100, 100, 4]
        assert result.items[2][-1] == updated
        # The third request restarts at page 0 with the window's lower bound moved to the newest
        # row seen — that is how the collection is walked past Auth0's 1000-result ceiling.
        assert result.requests[3].param("page") == "0"
        assert result.requests[3].param("q") == f'updated_at:["{newest}" TO *]'
        assert result.saved_states == [
            Auth0ResumeConfig(page=1, window_start=None),
            Auth0ResumeConfig(page=0, window_start=newest),
        ]
        assert result.committed_states == result.saved_states

    def test_window_that_cannot_advance_fails_loudly(self) -> None:
        stuck = "2024-06-01T00:00:00.000Z"
        page = {"users": _user_rows(100, stuck), "total": 200}

        with mock.patch.object(auth0_module, "SEARCH_RESULT_CAP", 200):
            result = self._run(
                "users",
                [ScriptedResponse(json=page), ScriptedResponse(json=page)],
                incremental_field="updated_at",
                db_incremental_field_last_value=stuck,
            )

        assert isinstance(result.raised, Auth0PaginationStalledError)
        assert result.final_state == Auth0ResumeConfig(page=1, window_start=stuck)

    def test_non_windowed_collection_never_slides(self) -> None:
        page_0 = {"clients": [{"client_id": str(i)} for i in range(100)], "total": 250}
        page_1 = {"clients": [{"client_id": str(i)} for i in range(100, 200)], "total": 250}
        page_2 = {"clients": [{"client_id": str(i)} for i in range(200, 250)], "total": 250}

        with mock.patch.object(auth0_module, "SEARCH_RESULT_CAP", 100):
            result = self._run(
                "clients",
                [ScriptedResponse(json=page_0), ScriptedResponse(json=page_1), ScriptedResponse(json=page_2)],
            )

        assert result.raised is None
        assert result.params("page")[1:] == ["0", "1", "2"]
        assert all(state.window_start is None for state in result.saved_states)

    def test_resumes_from_saved_page_and_window(self) -> None:
        resumed_window = "2024-07-01T00:00:00.000Z"
        page = {"users": _user_rows(1, "2024-07-02T00:00:00.000Z"), "total": 1}
        result = self._run(
            "users",
            [ScriptedResponse(json=page)],
            resume_state=Auth0ResumeConfig(page=4, window_start=resumed_window),
            incremental_field="updated_at",
            db_incremental_field_last_value="2020-01-01T00:00:00.000Z",
        )

        assert result.raised is None
        # The saved window wins over the (older) database watermark.
        assert result.requests[1].param("page") == "4"
        assert result.requests[1].param("q") == f'updated_at:["{resumed_window}" TO *]'

    def test_runaway_pagination_is_bounded(self) -> None:
        page = {"clients": [{"client_id": str(i)} for i in range(100)], "total": 10**9}

        with mock.patch.object(auth0_module, "MAX_PAGES", 2):
            result = self._run("clients", [ScriptedResponse(json=page)] * 3)

        assert isinstance(result.raised, Auth0PaginationLimitError)
        assert result.params("page")[1:] == ["0", "1"]

    def test_redirected_data_request_is_refused(self) -> None:
        result = self._run(
            "roles", [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/"})]
        )

        assert isinstance(result.raised, Auth0HostNotAllowedError)

    def test_redirected_data_request_is_refused_without_the_hook(self) -> None:
        with mock.patch.object(auth0_module, "_reject_redirect_response", lambda response, *args, **kwargs: response):
            result = self._run(
                "roles", [ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/"})]
            )

        assert isinstance(result.raised, Auth0HostNotAllowedError)

    def test_internal_domain_is_blocked_before_any_request(self) -> None:
        with mock.patch.object(auth0_module, "_is_host_safe", return_value=(False, "resolves to a private address")):
            result = self._run("roles", [], domain="internal.auth0.com")

        assert isinstance(result.raised, Auth0HostNotAllowedError)
        assert result.requests == []

    def test_fan_out_walks_each_parent_through_its_checkpoint_pages(self) -> None:
        orgs = {"organizations": [{"id": "org_1"}, {"id": "org_2"}, {"id": "org_3"}]}
        members_page_1 = {
            "members": [{"user_id": "auth0|1", "roles": [{"id": "rol_a", "name": "Admin"}]}],
            "next": "cp1",
        }
        members_page_2 = {
            "members": [
                {"user_id": "auth0|2", "roles": [{"id": "rol_a", "name": "Admin"}, {"id": "rol_b", "name": "Viewer"}]},
                {"user_id": "auth0|3", "roles": []},
            ]
        }
        result = self._run(
            "organization_member_roles",
            [
                ScriptedResponse(json=orgs),
                ScriptedResponse(json=members_page_1),
                ScriptedResponse(json=members_page_2),
                # Deleted after the organization page was read.
                ScriptedResponse(status=404),
                ScriptedResponse(json={"members": []}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"user_id": "auth0|1", "id": "rol_a", "name": "Admin", "organization_id": "org_1"},
            {"user_id": "auth0|2", "id": "rol_a", "name": "Admin", "organization_id": "org_1"},
            {"user_id": "auth0|2", "id": "rol_b", "name": "Viewer", "organization_id": "org_1"},
        ]
        assert result.paths[2:] == [
            "/api/v2/organizations/org_1/members",
            "/api/v2/organizations/org_1/members",
            "/api/v2/organizations/org_2/members",
            "/api/v2/organizations/org_3/members",
        ]
        assert result.params("from")[2:] == [None, "cp1", None, None]
        assert result.requests[2].param("fields") == "user_id,roles"
        # Without it Auth0 returns a bare array with no `next` token.
        assert set(result.params("include_totals")[1:]) == {"true"}
        assert result.saved_states == [
            Auth0ResumeConfig(page=0, last_parent_id=None, child_checkpoint="cp1"),
            Auth0ResumeConfig(page=0, last_parent_id="org_1"),
            Auth0ResumeConfig(page=0, last_parent_id="org_2"),
        ]

    def test_fan_out_over_users_escapes_the_user_id_and_slides_the_parent_window(self) -> None:
        users = {"users": [{"user_id": "auth0|1", "created_at": "2024-01-01T00:00:00.000Z"}], "total": 1}
        session = {"id": "sess_1", "user_id": "auth0|1", "created_at": "2024-02-01T00:00:00.000Z"}
        result = self._run(
            "user_sessions", [ScriptedResponse(json=users), ScriptedResponse(json={"sessions": [session]})]
        )

        assert result.raised is None
        assert result.rows == [session]
        assert result.requests[1].param("fields") == "user_id,created_at"
        assert result.requests[1].param("sort") == "created_at:1"
        assert result.paths[2] == "/api/v2/users/auth0%7C1/sessions"

    @pytest.mark.parametrize(
        "last_parent_id, child_checkpoint, expected_member_requests",
        [
            ("org_1", None, [("/api/v2/organizations/org_2/members", None)]),
            ("org_1", "cp9", [("/api/v2/organizations/org_2/members", "cp9")]),
            (
                None,
                "cp9",
                [("/api/v2/organizations/org_1/members", "cp9"), ("/api/v2/organizations/org_2/members", None)],
            ),
            # The resume parent left the page, so the whole page is read again rather than skipped.
            (
                "org_gone",
                "cp9",
                [("/api/v2/organizations/org_1/members", None), ("/api/v2/organizations/org_2/members", None)],
            ),
        ],
    )
    def test_fan_out_resumes_at_the_next_unread_child_page(
        self,
        last_parent_id: Optional[str],
        child_checkpoint: Optional[str],
        expected_member_requests: list[tuple[str, Optional[str]]],
    ) -> None:
        orgs = {"organizations": [{"id": "org_1"}, {"id": "org_2"}]}
        result = self._run(
            "organization_members",
            [ScriptedResponse(json=orgs), *[ScriptedResponse(json={"members": []})] * len(expected_member_requests)],
            resume_state=Auth0ResumeConfig(
                page=0, parent_checkpoint="cp_orgs", last_parent_id=last_parent_id, child_checkpoint=child_checkpoint
            ),
        )

        assert result.raised is None
        # Organizations are walked by checkpoint, so tenants with over 1000 of them are covered.
        assert result.requests[1].param("from") == "cp_orgs"
        assert result.requests[1].param("page") is None
        assert list(zip(result.paths[2:], result.params("from")[2:])) == expected_member_requests

    def test_role_members_omit_identity_provider_tokens(self) -> None:
        roles = {"roles": [{"id": "rol_1"}], "total": 1}
        member = {"user_id": "auth0|1", "identities": [{"provider": "google-oauth2", "access_token": "shh"}]}
        result = self._run("user_roles", [ScriptedResponse(json=roles), ScriptedResponse(json={"users": [member]})])

        assert result.raised is None
        assert result.rows == [
            {"user_id": "auth0|1", "identities": [{"provider": "google-oauth2"}], "role_id": "rol_1"}
        ]

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_propagate(self, status_code: int) -> None:
        result = self._run("roles", [ScriptedResponse(status=status_code)])

        assert isinstance(result.raised, requests.HTTPError)


class TestValidateCredentials:
    def _validate(
        self,
        *,
        post_response: ScriptedResponse,
        get_response: ScriptedResponse | None = None,
        schema_name: Optional[str] = None,
        domain: str = DOMAIN,
        host_safe: bool = True,
    ) -> tuple[bool, str | None]:
        script = [post_response, *([get_response] if get_response is not None else [])]
        with scripted_network(script):
            if not host_safe:
                with mock.patch.object(auth0_module, "_is_host_safe", return_value=(False, "private address")):
                    return validate_credentials(domain, "cid", "secret", "v2", schema_name=schema_name, team_id=1)
            return validate_credentials(domain, "cid", "secret", "v2", schema_name=schema_name, team_id=1)

    def test_token_exchange_alone_is_enough_at_source_create(self) -> None:
        assert self._validate(post_response=ScriptedResponse(json=TOKEN_JSON)) == (True, None)

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_bad_client_credentials_are_rejected(self, status_code: int) -> None:
        ok, error = self._validate(post_response=ScriptedResponse(status=status_code))
        assert ok is False
        assert error == "Invalid Auth0 client ID or client secret"

    @pytest.mark.parametrize("domain", ["", "   ", "https://", "tenant us auth0 com", "tenant.auth0.com:8080"])
    def test_malformed_domains_are_rejected(self, domain: str) -> None:
        assert self._validate(post_response=ScriptedResponse(json=TOKEN_JSON), domain=domain) == (
            False,
            "Invalid Auth0 domain",
        )

    def test_internal_domain_is_rejected(self) -> None:
        ok, error = self._validate(post_response=ScriptedResponse(json=TOKEN_JSON), host_safe=False)
        assert ok is False
        assert error == "private address"

    def test_scoped_probe_accepts_a_reachable_collection(self) -> None:
        result = self._validate(
            post_response=ScriptedResponse(json=TOKEN_JSON),
            get_response=ScriptedResponse(json={"users": [], "total": 0}),
            schema_name="users",
        )
        assert result == (True, None)

    @pytest.mark.parametrize(
        "endpoint, scope",
        [("users", "read:users"), ("logs", "read:logs"), ("log_streams", "read:log_streams")],
    )
    def test_scoped_probe_names_the_missing_scope(self, endpoint: str, scope: str) -> None:
        ok, error = self._validate(
            post_response=ScriptedResponse(json=TOKEN_JSON),
            get_response=ScriptedResponse(status=403),
            schema_name=endpoint,
        )
        assert ok is False
        assert error is not None
        assert scope in error

    @pytest.mark.parametrize(
        "parent_response, child_response, expected",
        [
            (ScriptedResponse(json={"organizations": [], "total": 0}), None, (True, None)),
            (
                ScriptedResponse(status=403),
                None,
                (
                    False,
                    "Your Auth0 application is missing the `read:organizations` scope for organization_members",
                ),
            ),
            (
                ScriptedResponse(json={"organizations": [{"id": "org_1"}], "total": 1}),
                ScriptedResponse(status=403),
                (
                    False,
                    "Your Auth0 application is missing the `read:organization_members` scope for organization_members",
                ),
            ),
            (
                ScriptedResponse(json={"organizations": [{"id": "org_1"}], "total": 1}),
                ScriptedResponse(json={"members": []}),
                (True, None),
            ),
        ],
    )
    def test_scoped_probe_of_a_child_collection_uses_a_real_parent(
        self,
        parent_response: ScriptedResponse,
        child_response: ScriptedResponse | None,
        expected: tuple[bool, str | None],
    ) -> None:
        script = [ScriptedResponse(json=TOKEN_JSON), parent_response, *([child_response] if child_response else [])]
        with scripted_network(script) as network:
            result = validate_credentials(DOMAIN, "cid", "secret", "v2", schema_name="organization_members", team_id=1)

        assert result == expected
        if child_response is not None:
            assert network.requests_log[-1].path == "/api/v2/organizations/org_1/members"

    def test_scoped_probe_refuses_a_redirect(self) -> None:
        ok, error = self._validate(
            post_response=ScriptedResponse(json=TOKEN_JSON),
            get_response=ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/"}),
            schema_name="roles",
        )
        assert (ok, error) == (False, auth0_module.HOST_NOT_ALLOWED_ERROR)

    def test_scoped_probe_refuses_a_redirect_without_the_hook(self) -> None:
        with mock.patch.object(auth0_module, "_reject_redirect_response", lambda response, *args, **kwargs: response):
            ok, error = self._validate(
                post_response=ScriptedResponse(json=TOKEN_JSON),
                get_response=ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/"}),
                schema_name="roles",
            )
        assert (ok, error) == (False, auth0_module.HOST_NOT_ALLOWED_ERROR)


class TestAuth0Source:
    def test_items_is_lazy(self) -> None:
        # Building the response must not touch the network; only iterating does.
        source = Auth0Source()
        inputs = source_inputs("roles")
        manager = source.get_resumable_source_manager(inputs)
        config = Auth0SourceConfig(auth0_domain=DOMAIN, client_id="cid", client_secret="secret")
        with scripted_network(
            [ScriptedResponse(json=TOKEN_JSON), ScriptedResponse(json={"roles": [], "total": 0})]
        ) as network:
            response = source.source_for_pipeline(config, manager, inputs)
            assert network.requests_log == []
            items = response.items()
            assert isinstance(items, Iterable)
            assert list(items) == []
            assert [request.path for request in network.requests_log] == ["/oauth/token", "/api/v2/roles"]
