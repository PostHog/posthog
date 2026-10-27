from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub import dockerhub
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.dockerhub import (
    DOCKERHUB_BASE_URL,
    PAGE_SIZE,
    DockerhubAuthExpiredError,
    DockerhubResumeConfig,
    DockerhubRetryableError,
    _audit_logs_url,
    _org_groups_url,
    _org_members_url,
    _repositories_url,
    _tags_url,
    check_access,
    check_endpoint_access,
    format_incremental_start,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import (
    DOCKERHUB_ENDPOINTS,
    ENDPOINTS,
    ORG_SCOPED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source import DockerhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dockerhub import (
    DockerhubSourceConfig,
)

# Call the undecorated functions so the tenacity retry/backoff wrappers don't slow failure-path tests.
_fetch_page_unwrapped = dockerhub._fetch_page.__wrapped__  # type: ignore[attr-defined]
_fetch_object_unwrapped = dockerhub._fetch_object.__wrapped__  # type: ignore[attr-defined]

REPOS_URL = _repositories_url("acme")
ALPHA_TAGS_URL = _tags_url("acme", "alpha")
BETA_TAGS_URL = _tags_url("acme", "beta")
MEMBERS_URL = _org_members_url("acme")
GROUPS_URL = _org_groups_url("acme")
ACTIONS_URL = f"{DOCKERHUB_BASE_URL}/v2/auditlogs/acme/actions"
LOGIN = ScriptedResponse(json={"token": "jwt-1"})


def _driver() -> SourceDriver:
    return SourceDriver(
        DockerhubSource(),
        DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token", namespace="acme"),
    )


def _page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"results": rows, "next": next_url})


def _audit_page(page: int, since: str | None = None) -> str:
    return _audit_logs_url("acme", page, since)


def _audit_events(count: int, *, action: str = "repo.tag.push") -> list[dict[str, Any]]:
    return [
        {"account": "acme", "action": action, "actor": "tom", "timestamp": f"2026-01-01T00:{i:02d}:00Z"}
        for i in range(count)
    ]


class _FakeResumableManager:
    def __init__(self, state: DockerhubResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DockerhubResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DockerhubResumeConfig | None:
        return self._state

    def save_state(self, data: DockerhubResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    def test_unknown_endpoint_raises(self, monkeypatch: Any) -> None:
        with pytest.raises(ValueError, match="Unknown Docker Hub endpoint 'nope'"):
            list(
                get_rows(
                    username="tom",
                    personal_access_token="dckr_pat_token",
                    namespace="acme",
                    endpoint="nope",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

    @pytest.mark.parametrize(
        ("endpoint", "initial_url"),
        [("repositories", REPOS_URL), ("org_members", MEMBERS_URL), ("org_groups", GROUPS_URL)],
    )
    def test_cursor_endpoint_follows_next_url_until_null(self, endpoint: str, initial_url: str) -> None:
        second = f"{initial_url}&page=2"
        result = _driver().run(endpoint, [LOGIN, _page([{"name": "alpha"}], second), _page([{"name": "beta"}])])
        assert result.raised is None
        assert result.rows == [{"name": "alpha"}, {"name": "beta"}]
        assert result.urls[1:] == [initial_url, second]
        # State is saved once, after the first page and pointing at the next cursor, then we stop.
        assert result.saved_states == [DockerhubResumeConfig(next_url=second)]

    @pytest.mark.parametrize(
        ("endpoint", "initial_url"),
        [("repositories", REPOS_URL), ("org_members", MEMBERS_URL), ("org_groups", GROUPS_URL)],
    )
    def test_cursor_endpoint_resumes_from_saved_cursor(self, endpoint: str, initial_url: str) -> None:
        second = f"{initial_url}&page=2"
        # The first page URL must never be fetched on resume.
        result = _driver().run(
            endpoint, [LOGIN, _page([{"name": "beta"}])], resume_state=DockerhubResumeConfig(next_url=second)
        )
        assert result.raised is None
        assert result.rows == [{"name": "beta"}]
        assert result.urls[1:] == [second]

    def test_tags_fan_out_injects_namespace_and_repository_name(self) -> None:
        result = _driver().run(
            "tags",
            [
                LOGIN,
                _page([{"name": "alpha"}, {"name": "beta"}]),
                _page([{"name": "latest", "repository": 42}]),
                _page([{"name": "v1"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [
            {"name": "latest", "repository": 42, "namespace": "acme", "repository_name": "alpha"},
            {"name": "v1", "namespace": "acme", "repository_name": "beta"},
        ]
        # State pins each completed repository so a crash re-syncs at most one repository.
        assert result.urls[1:] == [REPOS_URL, ALPHA_TAGS_URL, BETA_TAGS_URL]
        assert result.saved_states == [
            DockerhubResumeConfig(repository="alpha"),
            DockerhubResumeConfig(repository="beta"),
        ]

    def test_tags_saves_cursor_state_within_a_repository(self) -> None:
        alpha_page_2 = f"{DOCKERHUB_BASE_URL}/v2/namespaces/acme/repositories/alpha/tags?page=2&page_size=100"
        result = _driver().run(
            "tags", [LOGIN, _page([{"name": "alpha"}]), _page([{"name": "v2"}], alpha_page_2), _page([{"name": "v1"}])]
        )
        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["v2", "v1"]
        assert result.urls[1:] == [REPOS_URL, ALPHA_TAGS_URL, alpha_page_2]
        assert result.saved_states == [
            DockerhubResumeConfig(next_url=alpha_page_2, repository="alpha"),
            DockerhubResumeConfig(repository="alpha"),
        ]

    def test_tags_resumes_from_saved_repository_and_cursor(self) -> None:
        beta_page_2 = f"{DOCKERHUB_BASE_URL}/v2/namespaces/acme/repositories/beta/tags?page=2&page_size=100"
        result = _driver().run(
            "tags",
            [
                LOGIN,
                _page([{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}]),
                _page([{"name": "v1"}]),
                _page([{"name": "g1"}]),
            ],
            resume_state=DockerhubResumeConfig(next_url=beta_page_2, repository="beta"),
        )
        assert result.raised is None
        # alpha is skipped entirely; beta resumes mid-pagination; gamma starts fresh.
        assert [(row["repository_name"], row["name"]) for row in result.rows] == [("beta", "v1"), ("gamma", "g1")]
        assert result.urls[1:] == [REPOS_URL, beta_page_2, _tags_url("acme", "gamma")]

    def test_tags_restarts_when_resume_repository_was_deleted(self) -> None:
        result = _driver().run(
            "tags",
            [LOGIN, _page([{"name": "alpha"}]), _page([{"name": "latest"}])],
            resume_state=DockerhubResumeConfig(repository="deleted-repo"),
        )
        assert result.raised is None
        assert [(row["repository_name"], row["name"]) for row in result.rows] == [("alpha", "latest")]
        assert result.urls[1:] == [REPOS_URL, ALPHA_TAGS_URL]


class TestOrderingParams:
    def test_repositories_url_uses_ascending_name_ordering(self) -> None:
        # ordering=name is ascending on the repositories endpoint (verified live).
        assert "ordering=name" in REPOS_URL
        assert "ordering=-name" not in REPOS_URL

    def test_tags_url_uses_inverted_ordering_sign(self) -> None:
        # The tags endpoint inverts the sign: ordering=-name is ascending name (verified live).
        assert "ordering=-name" in ALPHA_TAGS_URL


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"results": [], "next": None}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(DockerhubRetryableError):
            _fetch_page_unwrapped(session, REPOS_URL, MagicMock())

    @parameterized.expand([("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, REPOS_URL, MagicMock())

    def test_unauthorized_raises_auth_expired_when_reauth_allowed(self) -> None:
        session = self._session_returning(401)
        with pytest.raises(DockerhubAuthExpiredError):
            _fetch_page_unwrapped(session, REPOS_URL, MagicMock())

    def test_unauthorized_raises_for_status_when_reauth_disallowed(self) -> None:
        session = self._session_returning(401)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, REPOS_URL, MagicMock(), allow_reauth=False)

    @parameterized.expand([("bare_list", [{"name": "a"}]), ("missing_results", {"count": 1})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(DockerhubRetryableError):
            _fetch_page_unwrapped(session, REPOS_URL, MagicMock())

    @parameterized.expand(
        [
            ("other_host", "https://attacker.example/v2/namespaces/acme/repositories"),
            ("http_scheme", "http://hub.docker.com/v2/namespaces/acme/repositories"),
        ]
    )
    def test_non_dockerhub_url_is_rejected_before_request(self, _name: str, url: str) -> None:
        session = self._session_returning(200)
        with pytest.raises(ValueError):
            _fetch_page_unwrapped(session, url, MagicMock())
        session.get.assert_not_called()

    def test_hostile_next_link_is_rejected(self) -> None:
        body = {"next": "https://attacker.example/v2/steal", "previous": None, "results": [{"name": "alpha"}]}
        session = self._session_returning(200, body)
        with pytest.raises(ValueError):
            _fetch_page_unwrapped(session, REPOS_URL, MagicMock())


class TestClientAuth:
    def test_login_failure_raises_http_error(self) -> None:
        result = _driver().run("repositories", [ScriptedResponse(status=401)])
        assert isinstance(result.raised, requests.HTTPError)
        assert [request.path for request in result.requests] == ["/v2/users/login"]

    def test_login_without_token_in_body_is_retryable(self) -> None:
        result = _driver().run("repositories", always(ScriptedResponse(json={"detail": "weird"})))
        assert isinstance(result.raised, DockerhubRetryableError)
        assert result.paths == ["/v2/users/login"] * 5

    def test_expired_jwt_triggers_single_relogin_and_retry(self) -> None:
        result = _driver().run(
            "repositories",
            [
                LOGIN,
                ScriptedResponse(status=401),
                ScriptedResponse(json={"token": "jwt-2"}),
                _page([{"name": "alpha"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"name": "alpha"}]
        assert result.paths == [
            "/v2/users/login",
            "/v2/namespaces/acme/repositories",
            "/v2/users/login",
            "/v2/namespaces/acme/repositories",
        ]
        assert [request.method for request in result.requests].count("POST") == 2
        assert result.requests[-1].headers["authorization"] == "Bearer jwt-2"

    def test_second_unauthorized_after_relogin_is_permanent(self) -> None:
        result = _driver().run(
            "repositories",
            [
                LOGIN,
                ScriptedResponse(status=401),
                ScriptedResponse(json={"token": "jwt-2"}),
                ScriptedResponse(status=401),
            ],
        )
        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == [
            "/v2/users/login",
            "/v2/namespaces/acme/repositories",
            "/v2/users/login",
            "/v2/namespaces/acme/repositories",
        ]


class TestCheckAccess:
    @parameterized.expand(
        [
            ("unauthorized", 401),
            ("forbidden", 403),
        ]
    )
    def test_login_auth_failures(self, _name: str, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert check_access("tom", "bad-token", "acme") == (status, None)
        assert [request.path for request in network.requests_log] == ["/v2/users/login"]

    @parameterized.expand(
        [
            # A bare status echo left the user nothing to act on; a 400 (Docker Hub rejects e.g. an
            # email in the username field) now points at the username/token, a 5xx reads as transient.
            ("bad_request", 400, "username"),
            ("server_error", 500, "temporarily unavailable"),
            ("unexpected", 418, "unexpected response"),
        ]
    )
    def test_login_unexpected_status_returns_actionable_message(
        self, _name: str, status: int, expected_substr: str
    ) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            result_status, message = check_access("tom", "token", "acme")
        assert [request.path for request in network.requests_log] == ["/v2/users/login"]
        assert result_status == status
        assert message is not None
        assert expected_substr in message
        assert message != f"Docker Hub returned HTTP {status}"

    def test_login_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            status, message = check_access("tom", "token", "acme")
        assert status == 0
        assert message is not None and "boom" in message
        assert {request.path for request in network.requests_log} == {"/v2/users/login"}

    def test_login_without_token_maps_to_zero(self) -> None:
        with scripted_network([ScriptedResponse(json={"detail": "weird"})]) as network:
            status, message = check_access("tom", "token", "acme")
        assert status == 0
        assert message == "Docker Hub login did not return a token"
        assert [request.path for request in network.requests_log] == ["/v2/users/login"]

    @parameterized.expand(
        [
            ("reachable", 200, 200, None),
            ("missing_namespace", 404, 404, "Docker Hub namespace 'acme' was not found"),
            (
                "no_namespace_access",
                403,
                403,
                "Your personal access token does not have access to the 'acme' namespace",
            ),
        ]
    )
    def test_namespace_probe_status_mapping(
        self, _name: str, probe_status: int, expected_status: int, expected_message: str | None
    ) -> None:
        with scripted_network([LOGIN, ScriptedResponse(status=probe_status)]) as network:
            assert check_access("tom", "token", "acme") == (expected_status, expected_message)
        assert [request.path for request in network.requests_log] == [
            "/v2/users/login",
            "/v2/namespaces/acme/repositories",
        ]
        assert network.requests_log[-1].param("page_size") == "1"

    @parameterized.expand(
        [
            ("ok", 200, None, True, None),
            ("bad_credentials", 401, None, False, "Invalid Docker Hub username or personal access token"),
            ("missing_namespace", 200, 404, False, "Docker Hub namespace 'acme' was not found"),
            (
                "no_namespace_access",
                200,
                403,
                False,
                "Your personal access token does not have access to the 'acme' namespace",
            ),
            (
                "server_error",
                500,
                None,
                False,
                "Docker Hub is temporarily unavailable (HTTP 500). Please try again in a few minutes.",
            ),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        login_status: int,
        probe_status: int | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        script = [ScriptedResponse(status=login_status, json={"token": "jwt-1"})]
        if login_status == 200:
            script.append(ScriptedResponse(status=probe_status or 200))
        with scripted_network(script) as network:
            assert validate_credentials("tom", "token", "acme") == (expected_valid, expected_message)
        assert network.requests_log[0].path == "/v2/users/login"
        assert len(network.requests_log) == (2 if login_status == 200 else 1)


class TestDockerhubSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        if endpoint == "audit_logs":
            answer = ScriptedResponse(json={"logs": []})
        elif endpoint == "audit_log_actions":
            answer = ScriptedResponse(json={"actions": {}})
        else:
            answer = _page([])
        result = _driver().run(endpoint, [LOGIN, answer])
        assert result.raised is None
        response = result.response
        assert response is not None
        config = DOCKERHUB_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        # Only the audit log has an immutable event timestamp to partition on. Repositories, tags,
        # members and groups carry mutable last_updated fields, which would rewrite partitions on
        # every sync.
        if config.partition_key:
            assert (response.partition_mode, response.partition_keys) == ("datetime", [config.partition_key])
        else:
            assert response.partition_mode is None

    def test_tags_primary_key_includes_parent_identifiers(self) -> None:
        # Tag names are only unique within a repository; without the injected parent identifiers in
        # the key, fan-out rows from different repositories would collide and corrupt merges.
        assert DOCKERHUB_ENDPOINTS["tags"].primary_keys == ["namespace", "repository_name", "name"]


class TestAuditLogs:
    def test_full_page_advances_and_saves_the_page_cursor(self) -> None:
        result = _driver().run(
            "audit_logs",
            [
                LOGIN,
                ScriptedResponse(json={"logs": _audit_events(PAGE_SIZE)}),
                ScriptedResponse(json={"logs": _audit_events(1)}),
            ],
        )
        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.urls[1:] == [_audit_page(1), _audit_page(2)]
        assert result.saved_states == [DockerhubResumeConfig(page=2)]

    def test_resumes_from_the_saved_page(self) -> None:
        result = _driver().run(
            "audit_logs",
            [LOGIN, ScriptedResponse(json={"logs": _audit_events(1)})],
            resume_state=DockerhubResumeConfig(page=3),
        )
        assert result.raised is None
        assert result.urls[1:] == [_audit_page(3)]

    def test_null_logs_ends_the_walk(self) -> None:
        # Docker Hub serializes an empty event list as null rather than [].
        result = _driver().run("audit_logs", [LOGIN, ScriptedResponse(json={"logs": None})])
        assert result.raised is None
        assert result.rows == []
        assert result.urls[1:] == [_audit_page(1)]

    def test_non_list_logs_is_retryable(self) -> None:
        result = _driver().run("audit_logs", [LOGIN, ScriptedResponse(json={"logs": {"unexpected": True}})])
        assert isinstance(result.raised, DockerhubRetryableError)
        assert result.urls[1:] == [_audit_page(1)]

    def test_incremental_run_sends_the_watermark_as_from(self) -> None:
        since = "2026-01-01T00:00:00Z"
        result = _driver().run(
            "audit_logs",
            [LOGIN, ScriptedResponse(json={"logs": _audit_events(1)})],
            incremental_field="timestamp",
            db_incremental_field_last_value=since,
        )
        assert result.raised is None
        assert result.urls[1:] == [_audit_page(1, since)]
        assert result.params("from") == [None, since]


class TestAuditLogActions:
    def test_action_map_is_flattened_into_joinable_rows(self) -> None:
        # An audit event names its action as "<group>.<name>", so the catalog is only usable as a
        # lookup once the joined form is on the row.
        result = _driver().run(
            "audit_log_actions",
            [
                LOGIN,
                ScriptedResponse(
                    json={
                        "actions": {
                            "repo": {
                                "label": "Repository",
                                "actions": [{"name": "tag.push", "label": "Tag Pushed", "description": "Tags pushed"}],
                            },
                            "org": {
                                "label": "Organization",
                                "actions": [{"name": "member.add", "label": "Member Added"}],
                            },
                        }
                    },
                ),
            ],
        )
        assert result.raised is None
        assert result.urls[1:] == [ACTIONS_URL]
        assert result.rows == [
            {
                "action_group": "repo",
                "action_group_label": "Repository",
                "name": "tag.push",
                "qualified_name": "repo.tag.push",
                "label": "Tag Pushed",
                "description": "Tags pushed",
            },
            {
                "action_group": "org",
                "action_group_label": "Organization",
                "name": "member.add",
                "qualified_name": "org.member.add",
                "label": "Member Added",
                "description": None,
            },
        ]

    @pytest.mark.parametrize("body", [{}, {"actions": []}])
    def test_unexpected_payload_is_retryable(self, body: Any) -> None:
        result = _driver().run("audit_log_actions", [LOGIN, ScriptedResponse(json=body)])
        assert isinstance(result.raised, DockerhubRetryableError)
        assert result.urls[1:] == [ACTIONS_URL]


class TestFormatIncrementalStart:
    @parameterized.expand(
        [
            ("none", None, None),
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            # A naive watermark is UTC; reading it as local time would shift the window by hours and
            # either skip events or re-pull a day of them.
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            (
                "other_zone_datetime",
                datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2))),
                "2026-01-02T01:04:05Z",
            ),
            ("string_passthrough", "2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
            ("blank_string", "   ", None),
        ]
    )
    def test_watermark_is_rendered_as_an_rfc_3339_instant(self, _name: str, value: Any, expected: Any) -> None:
        assert format_incremental_start(value) == expected


class TestCheckEndpointAccess:
    def test_repositories_and_tags_are_never_probed(self) -> None:
        # Both read the namespace endpoints that `validate_credentials` already covered, so probing
        # them again would spend requests to report what the source-level check reports.
        with scripted_network([]) as network:
            assert check_endpoint_access("tom", "token", "acme", ["repositories", "tags"]) == {
                "repositories": None,
                "tags": None,
            }
        assert network.requests_log == []

    @parameterized.expand(
        [
            ("personal_namespace", 404, "returned no organization named"),
            ("missing_org_scope", 403, "cannot read organization data"),
        ]
    )
    def test_unreachable_org_endpoints_report_what_to_change(
        self, _name: str, status: int, expected_substr: str
    ) -> None:
        with scripted_network([LOGIN, *[ScriptedResponse(status=status) for _ in ORG_SCOPED_ENDPOINTS]]) as network:
            permissions = check_endpoint_access("tom", "token", "acme", list(ENDPOINTS))
        assert permissions["repositories"] is None
        assert len(network.requests_log) == 1 + len(ORG_SCOPED_ENDPOINTS)
        assert network.requests_log[0].path == "/v2/users/login"
        for endpoint in ORG_SCOPED_ENDPOINTS:
            reason = permissions[endpoint]
            assert reason is not None and expected_substr in reason

    @parameterized.expand(
        [
            ("rejected_login", 401, None),
            ("probe_connection_error", 200, requests.ConnectionError("boom")),
        ]
    )
    def test_transient_and_credential_failures_do_not_block_the_picker(
        self, _name: str, login_status: int, probe: Any
    ) -> None:
        # A bad credential is reported by validate_credentials, and a network blip is not a missing
        # permission. Either one marking every org table unavailable would be a false alarm.
        if login_status == 200:
            assert isinstance(probe, BaseException)

            def answer(request: RecordedRequest) -> ScriptedResponse:
                if request.path == "/v2/users/login":
                    return LOGIN
                raise probe

            script: Script = answer
        else:
            script = [ScriptedResponse(status=login_status)]
        with scripted_network(script) as network:
            assert check_endpoint_access("tom", "token", "acme", list(ENDPOINTS)) == dict.fromkeys(ENDPOINTS)
        paths = {request.path for request in network.requests_log}
        expected_paths = {"/v2/users/login"}
        if login_status == 200:
            expected_paths.update(
                {
                    "/v2/orgs/acme/members",
                    "/v2/orgs/acme/groups",
                    "/v2/auditlogs/acme",
                    "/v2/auditlogs/acme/actions",
                }
            )
        assert paths == expected_paths


class TestFetchObject:
    def test_non_object_payload_is_retryable(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = [{"name": "alpha"}]
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(DockerhubRetryableError):
            _fetch_object_unwrapped(session, ACTIONS_URL, MagicMock())

    def test_expired_jwt_triggers_a_relogin_and_retry(self) -> None:
        # The audit log endpoints go through get_object, so they need the same mid-sync JWT refresh
        # the list endpoints get. Without it a long audit log walk dies at token expiry.
        result = _driver().run(
            "audit_log_actions",
            [
                LOGIN,
                ScriptedResponse(status=401),
                ScriptedResponse(json={"token": "jwt-2"}),
                ScriptedResponse(json={"actions": {}}),
            ],
        )
        assert result.raised is None
        assert result.rows == []
        assert result.paths == [
            "/v2/users/login",
            "/v2/auditlogs/acme/actions",
            "/v2/users/login",
            "/v2/auditlogs/acme/actions",
        ]
        assert result.requests[-1].headers["authorization"] == "Bearer jwt-2"
