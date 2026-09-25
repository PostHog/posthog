from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub import dockerhub
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.dockerhub import (
    DOCKERHUB_BASE_URL,
    PAGE_SIZE,
    DockerhubAuthExpiredError,
    DockerHubClient,
    DockerhubResumeConfig,
    DockerhubRetryableError,
    _audit_logs_url,
    _org_groups_url,
    _org_members_url,
    _repositories_url,
    _tags_url,
    check_access,
    check_endpoint_access,
    dockerhub_source,
    format_incremental_start,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import (
    DOCKERHUB_ENDPOINTS,
    ENDPOINTS,
    ORG_SCOPED_ENDPOINTS,
)

# Call the undecorated functions so the tenacity retry/backoff wrappers don't slow failure-path tests.
_fetch_page_unwrapped = dockerhub._fetch_page.__wrapped__  # type: ignore[attr-defined]
_fetch_jwt_unwrapped = dockerhub._fetch_jwt.__wrapped__  # type: ignore[attr-defined]
_fetch_object_unwrapped = dockerhub._fetch_object.__wrapped__  # type: ignore[attr-defined]

REPOS_URL = _repositories_url("acme")
ALPHA_TAGS_URL = _tags_url("acme", "alpha")
BETA_TAGS_URL = _tags_url("acme", "beta")
MEMBERS_URL = _org_members_url("acme")
GROUPS_URL = _org_groups_url("acme")
ACTIONS_URL = f"{DOCKERHUB_BASE_URL}/v2/auditlogs/acme/actions"


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


class _FakeClient:
    def __init__(
        self,
        pages: Mapping[str, tuple[list[dict[str, Any]], Optional[str]]],
        objects: Mapping[str, dict[str, Any]] | None = None,
    ) -> None:
        self._pages = pages
        self._objects = objects or {}
        self.fetched: list[str] = []
        self.login_calls = 0

    def login(self) -> None:
        self.login_calls += 1

    def get_page(self, url: str) -> tuple[list[dict[str, Any]], Optional[str]]:
        self.fetched.append(url)
        return self._pages[url]

    def get_object(self, url: str) -> dict[str, Any]:
        self.fetched.append(url)
        return self._objects[url]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, tuple[list[dict[str, Any]], Optional[str]]],
        endpoint: str,
        objects: Mapping[str, dict[str, Any]] | None = None,
        incremental_start: str | None = None,
    ) -> tuple[list[dict[str, Any]], _FakeClient]:
        client = _FakeClient(pages, objects)
        monkeypatch.setattr(dockerhub, "DockerHubClient", lambda *args, **kwargs: client)

        rows: list[dict[str, Any]] = []
        for batch in get_rows(
            username="tom",
            personal_access_token="dckr_pat_token",
            namespace="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            incremental_start=incremental_start,
        ):
            rows.extend(batch)
        return rows, client

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

    # pytest.mark.parametrize, not parameterized.expand: these cases take the monkeypatch fixture.
    @pytest.mark.parametrize(
        ("endpoint", "initial_url"),
        [("repositories", REPOS_URL), ("org_members", MEMBERS_URL), ("org_groups", GROUPS_URL)],
    )
    def test_cursor_endpoint_single_page_yields_and_stops(
        self, endpoint: str, initial_url: str, monkeypatch: Any
    ) -> None:
        manager = _FakeResumableManager()
        pages = {initial_url: ([{"id": "1", "namespace": "acme", "name": "alpha"}], None)}
        rows, client = self._collect(manager, monkeypatch, pages, endpoint)
        assert rows == [{"id": "1", "namespace": "acme", "name": "alpha"}]
        assert client.fetched == [initial_url]
        assert client.login_calls == 1
        # A null next link ends the sync without persisting resume state.
        assert manager.saved == []

    @pytest.mark.parametrize(
        ("endpoint", "initial_url"),
        [("repositories", REPOS_URL), ("org_members", MEMBERS_URL), ("org_groups", GROUPS_URL)],
    )
    def test_cursor_endpoint_follows_next_url_until_null(
        self, endpoint: str, initial_url: str, monkeypatch: Any
    ) -> None:
        manager = _FakeResumableManager()
        second = f"{initial_url}&page=2"
        pages = {
            initial_url: ([{"name": "alpha"}], second),
            second: ([{"name": "beta"}], None),
        }
        rows, _ = self._collect(manager, monkeypatch, pages, endpoint)
        assert rows == [{"name": "alpha"}, {"name": "beta"}]
        # State is saved once, after the first page and pointing at the next cursor, then we stop.
        assert [(s.next_url, s.repository) for s in manager.saved] == [(second, None)]

    @pytest.mark.parametrize(
        ("endpoint", "initial_url"),
        [("repositories", REPOS_URL), ("org_members", MEMBERS_URL), ("org_groups", GROUPS_URL)],
    )
    def test_cursor_endpoint_resumes_from_saved_cursor(self, endpoint: str, initial_url: str, monkeypatch: Any) -> None:
        second = f"{initial_url}&page=2"
        manager = _FakeResumableManager(DockerhubResumeConfig(next_url=second))
        # The first page URL must never be fetched on resume.
        pages = {second: ([{"name": "beta"}], None)}
        rows, client = self._collect(manager, monkeypatch, pages, endpoint)
        assert rows == [{"name": "beta"}]
        assert client.fetched == [second]

    def test_tags_fan_out_injects_namespace_and_repository_name(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: Mapping[str, tuple[list[dict[str, Any]], Optional[str]]] = {
            REPOS_URL: ([{"name": "alpha"}, {"name": "beta"}], None),
            ALPHA_TAGS_URL: ([{"name": "latest", "repository": 42}], None),
            BETA_TAGS_URL: ([{"name": "v1"}], None),
        }
        rows, _ = self._collect(manager, monkeypatch, pages, "tags")
        assert rows == [
            {"name": "latest", "repository": 42, "namespace": "acme", "repository_name": "alpha"},
            {"name": "v1", "namespace": "acme", "repository_name": "beta"},
        ]
        # State pins each completed repository so a crash re-syncs at most one repository.
        assert [(s.repository, s.next_url) for s in manager.saved] == [("alpha", None), ("beta", None)]

    def test_tags_saves_cursor_state_within_a_repository(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        alpha_page_2 = f"{DOCKERHUB_BASE_URL}/v2/namespaces/acme/repositories/alpha/tags?page=2&page_size=100"
        pages = {
            REPOS_URL: ([{"name": "alpha"}], None),
            ALPHA_TAGS_URL: ([{"name": "v2"}], alpha_page_2),
            alpha_page_2: ([{"name": "v1"}], None),
        }
        rows, _ = self._collect(manager, monkeypatch, pages, "tags")
        assert [r["name"] for r in rows] == ["v2", "v1"]
        assert [(s.repository, s.next_url) for s in manager.saved] == [
            ("alpha", alpha_page_2),
            ("alpha", None),
        ]

    def test_tags_resumes_from_saved_repository_and_cursor(self, monkeypatch: Any) -> None:
        beta_page_2 = f"{DOCKERHUB_BASE_URL}/v2/namespaces/acme/repositories/beta/tags?page=2&page_size=100"
        manager = _FakeResumableManager(DockerhubResumeConfig(next_url=beta_page_2, repository="beta"))
        pages = {
            REPOS_URL: ([{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}], None),
            beta_page_2: ([{"name": "v1"}], None),
            _tags_url("acme", "gamma"): ([{"name": "g1"}], None),
        }
        rows, client = self._collect(manager, monkeypatch, pages, "tags")
        # alpha is skipped entirely; beta resumes mid-pagination; gamma starts fresh.
        assert [(r["repository_name"], r["name"]) for r in rows] == [("beta", "v1"), ("gamma", "g1")]
        assert ALPHA_TAGS_URL not in client.fetched
        assert BETA_TAGS_URL not in client.fetched

    def test_tags_restarts_when_resume_repository_was_deleted(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(DockerhubResumeConfig(next_url=None, repository="deleted-repo"))
        pages = {
            REPOS_URL: ([{"name": "alpha"}], None),
            ALPHA_TAGS_URL: ([{"name": "latest"}], None),
        }
        rows, _ = self._collect(manager, monkeypatch, pages, "tags")
        assert [(r["repository_name"], r["name"]) for r in rows] == [("alpha", "latest")]


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

    def test_success_returns_results_and_next(self) -> None:
        next_url = f"{REPOS_URL}&page=2"
        body = {"count": 5, "next": next_url, "previous": None, "results": [{"name": "alpha"}]}
        session = self._session_returning(200, body)
        rows, returned_next = _fetch_page_unwrapped(session, REPOS_URL, MagicMock())
        assert rows == [{"name": "alpha"}]
        assert returned_next == next_url

    def test_null_next_returns_none(self) -> None:
        body = {"count": 1, "next": None, "previous": None, "results": [{"name": "alpha"}]}
        session = self._session_returning(200, body)
        _, returned_next = _fetch_page_unwrapped(session, REPOS_URL, MagicMock())
        assert returned_next is None

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
    def _login_response(self, status_code: int = 200, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"token": "jwt-1"}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        return response

    def _page_response(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"results": [{"name": "alpha"}], "next": None}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        return response

    def _client_with_session(self, session: MagicMock) -> DockerHubClient:
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            return DockerHubClient("tom", "dckr_pat_token", MagicMock())

    def test_login_sets_bearer_token_from_exchanged_jwt(self) -> None:
        session = MagicMock()
        session.headers = {}
        session.post.return_value = self._login_response()
        client = self._client_with_session(session)
        client.login()
        assert session.headers["Authorization"] == "Bearer jwt-1"
        args, kwargs = session.post.call_args
        assert args[0] == f"{DOCKERHUB_BASE_URL}/v2/users/login"
        assert kwargs["json"] == {"username": "tom", "password": "dckr_pat_token"}

    def test_login_failure_raises_http_error(self) -> None:
        session = MagicMock()
        session.headers = {}
        session.post.return_value = self._login_response(status_code=401)
        client = self._client_with_session(session)
        with pytest.raises(requests.HTTPError):
            client.login()

    def test_login_without_token_in_body_is_retryable(self) -> None:
        session = MagicMock()
        session.post.return_value = self._login_response(body={"detail": "weird"})
        with pytest.raises(DockerhubRetryableError):
            _fetch_jwt_unwrapped(session, "tom", "dckr_pat_token", MagicMock())

    def test_expired_jwt_triggers_single_relogin_and_retry(self) -> None:
        session = MagicMock()
        session.headers = {}
        session.post.side_effect = [
            self._login_response(body={"token": "jwt-1"}),
            self._login_response(body={"token": "jwt-2"}),
        ]
        session.get.side_effect = [self._page_response(401), self._page_response(200)]
        client = self._client_with_session(session)
        client.login()

        rows, next_url = client.get_page(REPOS_URL)

        assert rows == [{"name": "alpha"}]
        assert next_url is None
        assert session.post.call_count == 2
        assert session.headers["Authorization"] == "Bearer jwt-2"

    def test_second_unauthorized_after_relogin_is_permanent(self) -> None:
        session = MagicMock()
        session.headers = {}
        session.post.side_effect = [
            self._login_response(body={"token": "jwt-1"}),
            self._login_response(body={"token": "jwt-2"}),
        ]
        session.get.side_effect = [self._page_response(401), self._page_response(401)]
        client = self._client_with_session(session)
        client.login()

        with pytest.raises(requests.HTTPError):
            client.get_page(REPOS_URL)


class TestCheckAccess:
    def _response(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"token": "jwt-1"}
        return response

    def _session(self, login_response: Any, probe_response: Any = None) -> MagicMock:
        session = MagicMock()
        if isinstance(login_response, Exception):
            session.post.side_effect = login_response
        else:
            session.post.return_value = login_response
        if isinstance(probe_response, Exception):
            session.get.side_effect = probe_response
        elif probe_response is not None:
            session.get.return_value = probe_response
        return session

    @parameterized.expand(
        [
            ("unauthorized", 401),
            ("forbidden", 403),
        ]
    )
    def test_login_auth_failures(self, _name: str, status: int) -> None:
        session = self._session(self._response(status))
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            assert check_access("tom", "bad-token", "acme") == (status, None)

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
        session = self._session(self._response(status))
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            result_status, message = check_access("tom", "token", "acme")
        assert result_status == status
        assert message is not None
        assert expected_substr in message
        assert message != f"Docker Hub returned HTTP {status}"

    def test_login_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            status, message = check_access("tom", "token", "acme")
        assert status == 0
        assert message is not None and "boom" in message

    def test_login_without_token_maps_to_zero(self) -> None:
        session = self._session(self._response(200, body={"detail": "weird"}))
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            status, message = check_access("tom", "token", "acme")
        assert status == 0
        assert message == "Docker Hub login did not return a token"

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
        session = self._session(self._response(200), self._response(probe_status))
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            assert check_access("tom", "token", "acme") == (expected_status, expected_message)

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
        probe_response = self._response(probe_status) if probe_status is not None else self._response(200)
        session = self._session(self._response(login_status), probe_response)
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            assert validate_credentials("tom", "token", "acme") == (expected_valid, expected_message)


class TestDockerhubSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = dockerhub_source(
            username="tom",
            personal_access_token="dckr_pat_token",
            namespace="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
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

    def test_repositories_primary_key_is_namespace_scoped(self) -> None:
        assert DOCKERHUB_ENDPOINTS["repositories"].primary_keys == ["namespace", "name"]


class TestAuditLogs:
    def test_short_page_ends_the_walk(self, monkeypatch: Any) -> None:
        # The endpoint returns no next link and no total count, so a page shorter than page_size is
        # the only end-of-collection signal. Missing it loops forever on an empty page.
        manager = _FakeResumableManager()
        objects = {_audit_page(1): {"logs": _audit_events(2)}}
        rows, client = TestGetRows._collect(manager, monkeypatch, {}, "audit_logs", objects=objects)
        assert len(rows) == 2
        assert client.fetched == [_audit_page(1)]
        assert manager.saved == []

    def test_full_page_advances_and_saves_the_page_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        objects = {
            _audit_page(1): {"logs": _audit_events(PAGE_SIZE)},
            _audit_page(2): {"logs": _audit_events(1)},
        }
        rows, client = TestGetRows._collect(manager, monkeypatch, {}, "audit_logs", objects=objects)
        assert len(rows) == PAGE_SIZE + 1
        assert client.fetched == [_audit_page(1), _audit_page(2)]
        assert [state.page for state in manager.saved] == [2]

    def test_resumes_from_the_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(DockerhubResumeConfig(page=3))
        objects = {_audit_page(3): {"logs": _audit_events(1)}}
        _, client = TestGetRows._collect(manager, monkeypatch, {}, "audit_logs", objects=objects)
        assert client.fetched == [_audit_page(3)]

    def test_null_logs_ends_the_walk(self, monkeypatch: Any) -> None:
        # Docker Hub serializes an empty event list as null rather than [].
        manager = _FakeResumableManager()
        objects: dict[str, Any] = {_audit_page(1): {"logs": None}}
        rows, _ = TestGetRows._collect(manager, monkeypatch, {}, "audit_logs", objects=objects)
        assert rows == []

    def test_non_list_logs_is_retryable(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        objects: dict[str, Any] = {_audit_page(1): {"logs": {"unexpected": True}}}
        with pytest.raises(DockerhubRetryableError):
            TestGetRows._collect(manager, monkeypatch, {}, "audit_logs", objects=objects)

    def test_incremental_run_sends_the_watermark_as_from(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        since = "2026-01-01T00:00:00Z"
        objects = {_audit_page(1, since): {"logs": _audit_events(1)}}
        _, client = TestGetRows._collect(
            manager, monkeypatch, {}, "audit_logs", objects=objects, incremental_start=since
        )
        assert "from=2026-01-01T00%3A00%3A00Z" in client.fetched[0]

    def test_full_refresh_run_omits_from(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        objects = {_audit_page(1): {"logs": _audit_events(1)}}
        _, client = TestGetRows._collect(manager, monkeypatch, {}, "audit_logs", objects=objects)
        assert "from=" not in client.fetched[0]

    def test_synthetic_id_is_stable_for_identical_events(self, monkeypatch: Any) -> None:
        # The endpoint returns no event id. An id that is not a pure function of the row's content
        # would make every incremental run re-insert the boundary rows instead of merging onto them.
        event = _audit_events(1)[0]
        first, _ = TestGetRows._collect(
            _FakeResumableManager(), monkeypatch, {}, "audit_logs", objects={_audit_page(1): {"logs": [event]}}
        )
        second, _ = TestGetRows._collect(
            _FakeResumableManager(), monkeypatch, {}, "audit_logs", objects={_audit_page(1): {"logs": [dict(event)]}}
        )
        assert first[0]["id"] == second[0]["id"]

    def test_synthetic_id_changes_with_the_event(self, monkeypatch: Any) -> None:
        rows, _ = TestGetRows._collect(
            _FakeResumableManager(),
            monkeypatch,
            {},
            "audit_logs",
            objects={_audit_page(1): {"logs": _audit_events(2)}},
        )
        assert rows[0]["id"] != rows[1]["id"]

    def test_synthetic_id_ignores_an_id_the_api_starts_returning(self, monkeypatch: Any) -> None:
        # If Docker Hub ever adds its own `id`, hashing it in would change every key at once and
        # re-insert the whole table. The hash covers the event body only.
        event = _audit_events(1)[0]
        plain, _ = TestGetRows._collect(
            _FakeResumableManager(), monkeypatch, {}, "audit_logs", objects={_audit_page(1): {"logs": [event]}}
        )
        with_id, _ = TestGetRows._collect(
            _FakeResumableManager(),
            monkeypatch,
            {},
            "audit_logs",
            objects={_audit_page(1): {"logs": [{**event, "id": "hub-side-id"}]}},
        )
        assert plain[0]["id"] == with_id[0]["id"]


class TestAuditLogActions:
    def test_action_map_is_flattened_into_joinable_rows(self, monkeypatch: Any) -> None:
        # An audit event names its action as "<group>.<name>", so the catalog is only usable as a
        # lookup once the joined form is on the row.
        objects = {
            ACTIONS_URL: {
                "actions": {
                    "repo": {
                        "label": "Repository",
                        "actions": [{"name": "tag.push", "label": "Tag Pushed", "description": "Tags pushed"}],
                    },
                    "org": {"label": "Organization", "actions": [{"name": "member.add", "label": "Member Added"}]},
                }
            }
        }
        rows, _ = TestGetRows._collect(_FakeResumableManager(), monkeypatch, {}, "audit_log_actions", objects=objects)
        assert rows == [
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
    def test_unexpected_payload_is_retryable(self, body: Any, monkeypatch: Any) -> None:
        with pytest.raises(DockerhubRetryableError):
            TestGetRows._collect(
                _FakeResumableManager(), monkeypatch, {}, "audit_log_actions", objects={ACTIONS_URL: body}
            )

    def test_group_without_actions_yields_nothing(self, monkeypatch: Any) -> None:
        objects: dict[str, Any] = {ACTIONS_URL: {"actions": {"repo": {"label": "Repository"}}}}
        rows, _ = TestGetRows._collect(_FakeResumableManager(), monkeypatch, {}, "audit_log_actions", objects=objects)
        assert rows == []


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
    def _sessions(self, login_status: int = 200, probe: Any = None) -> MagicMock:
        session = MagicMock()
        login = MagicMock()
        login.ok = login_status < 400
        login.json.return_value = {"token": "jwt-1"}
        session.post.return_value = login
        if isinstance(probe, Exception):
            session.get.side_effect = probe
        elif probe is not None:
            response = MagicMock()
            response.status_code = probe
            session.get.return_value = response
        return session

    def _check(self, session: MagicMock, endpoints: list[str] | None = None) -> dict[str, str | None]:
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            return check_endpoint_access("tom", "token", "acme", endpoints or list(ENDPOINTS))

    def test_repositories_and_tags_are_never_probed(self) -> None:
        # Both read the namespace endpoints that `validate_credentials` already covered, so probing
        # them again would spend requests to report what the source-level check reports.
        session = self._sessions()
        assert self._check(session, ["repositories", "tags"]) == {"repositories": None, "tags": None}
        session.post.assert_not_called()

    @parameterized.expand(
        [
            ("personal_namespace", 404, "returned no organization named"),
            ("missing_org_scope", 403, "cannot read organization data"),
        ]
    )
    def test_unreachable_org_endpoints_report_what_to_change(
        self, _name: str, status: int, expected_substr: str
    ) -> None:
        permissions = self._check(self._sessions(probe=status))
        assert permissions["repositories"] is None
        for endpoint in ORG_SCOPED_ENDPOINTS:
            reason = permissions[endpoint]
            assert reason is not None and expected_substr in reason

    def test_reachable_org_endpoints_report_no_reason(self) -> None:
        assert self._check(self._sessions(probe=200)) == dict.fromkeys(ENDPOINTS)

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
        assert self._check(self._sessions(login_status=login_status, probe=probe)) == dict.fromkeys(ENDPOINTS)


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
        session = MagicMock()
        session.headers = {}
        login = MagicMock()
        login.status_code = 200
        login.ok = True
        login.json.return_value = {"token": "jwt-2"}
        session.post.return_value = login

        expired = MagicMock(status_code=401, ok=False, text="")
        expired.raise_for_status.side_effect = requests.HTTPError("401 error", response=expired)
        fresh = MagicMock(status_code=200, ok=True, text="")
        fresh.json.return_value = {"actions": {}}
        session.get.side_effect = [expired, fresh]

        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            client = DockerHubClient("tom", "dckr_pat_token", MagicMock())

        assert client.get_object(ACTIONS_URL) == {"actions": {}}
        assert session.headers["Authorization"] == "Bearer jwt-2"
