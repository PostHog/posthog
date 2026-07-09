from collections.abc import Mapping
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub import dockerhub
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.dockerhub import (
    DOCKERHUB_BASE_URL,
    DockerhubAuthExpiredError,
    DockerHubClient,
    DockerhubResumeConfig,
    DockerhubRetryableError,
    _repositories_url,
    _tags_url,
    check_access,
    dockerhub_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import (
    DOCKERHUB_ENDPOINTS,
    ENDPOINTS,
)

# Call the undecorated functions so the tenacity retry/backoff wrappers don't slow failure-path tests.
_fetch_page_unwrapped = dockerhub._fetch_page.__wrapped__  # type: ignore[attr-defined]
_fetch_jwt_unwrapped = dockerhub._fetch_jwt.__wrapped__  # type: ignore[attr-defined]

REPOS_URL = _repositories_url("acme")
ALPHA_TAGS_URL = _tags_url("acme", "alpha")
BETA_TAGS_URL = _tags_url("acme", "beta")


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
    def __init__(self, pages: Mapping[str, tuple[list[dict[str, Any]], Optional[str]]]) -> None:
        self._pages = pages
        self.fetched: list[str] = []
        self.login_calls = 0

    def login(self) -> None:
        self.login_calls += 1

    def get_page(self, url: str) -> tuple[list[dict[str, Any]], Optional[str]]:
        self.fetched.append(url)
        return self._pages[url]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: Mapping[str, tuple[list[dict[str, Any]], Optional[str]]],
        endpoint: str,
    ) -> tuple[list[dict[str, Any]], _FakeClient]:
        client = _FakeClient(pages)
        monkeypatch.setattr(dockerhub, "DockerHubClient", lambda *args, **kwargs: client)

        rows: list[dict[str, Any]] = []
        for batch in get_rows(
            username="tom",
            personal_access_token="dckr_pat_token",
            namespace="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
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

    def test_repositories_single_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {REPOS_URL: ([{"namespace": "acme", "name": "alpha"}], None)}
        rows, client = self._collect(manager, monkeypatch, pages, "repositories")
        assert rows == [{"namespace": "acme", "name": "alpha"}]
        assert client.login_calls == 1
        # A null next link ends the sync without persisting resume state.
        assert manager.saved == []

    def test_repositories_follows_next_url_until_null(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        second = f"{DOCKERHUB_BASE_URL}/v2/namespaces/acme/repositories?ordering=name&page=2&page_size=100"
        pages = {
            REPOS_URL: ([{"name": "alpha"}], second),
            second: ([{"name": "beta"}], None),
        }
        rows, _ = self._collect(manager, monkeypatch, pages, "repositories")
        assert rows == [{"name": "alpha"}, {"name": "beta"}]
        # State is saved once — after the first page, pointing at the next cursor — then we stop.
        assert [(s.next_url, s.repository) for s in manager.saved] == [(second, None)]

    def test_repositories_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        second = f"{DOCKERHUB_BASE_URL}/v2/namespaces/acme/repositories?ordering=name&page=2&page_size=100"
        manager = _FakeResumableManager(DockerhubResumeConfig(next_url=second))
        # The first page URL must never be fetched on resume.
        pages = {second: ([{"name": "beta"}], None)}
        rows, client = self._collect(manager, monkeypatch, pages, "repositories")
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

    def test_login_server_error_returns_status_and_message(self) -> None:
        session = self._session(self._response(500))
        with patch.object(dockerhub, "make_tracked_session", return_value=session):
            assert check_access("tom", "token", "acme") == (500, "Docker Hub returned HTTP 500")

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
            ("server_error", 500, None, False, "Docker Hub returned HTTP 500"),
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
        assert response.name == endpoint
        assert response.primary_keys == DOCKERHUB_ENDPOINTS[endpoint].primary_keys
        # Repositories and tags carry mutable last_updated timestamps only; we don't partition.
        assert response.partition_mode is None

    def test_tags_primary_key_includes_parent_identifiers(self) -> None:
        # Tag names are only unique within a repository; without the injected parent identifiers in
        # the key, fan-out rows from different repositories would collide and corrupt merges.
        assert DOCKERHUB_ENDPOINTS["tags"].primary_keys == ["namespace", "repository_name", "name"]

    def test_repositories_primary_key_is_namespace_scoped(self) -> None:
        assert DOCKERHUB_ENDPOINTS["repositories"].primary_keys == ["namespace", "name"]
