from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codacy import codacy
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.codacy import (
    CodacyRetryableError,
    _fetch_page,
    codacy_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.settings import CODACY_ENDPOINTS, ENDPOINTS

BASE = "https://api.codacy.com/api/v3"
REPOS_URL = f"{BASE}/organizations/gh/acme/repositories?limit=100"


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


def _collect(monkeypatch: Any, endpoint: str, pages: dict[str, Any]) -> list[dict]:
    """Run get_rows against URL-keyed fixtures; a request for an unexpected URL fails loudly."""

    def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(codacy, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(api_token="token", provider="gh", organization="acme", endpoint=endpoint, logger=MagicMock()):
        rows.extend(batch)
    return rows


class TestPagination:
    def test_follows_cursor_until_final_page_omits_it(self, monkeypatch: Any) -> None:
        orgs_url = f"{BASE}/user/organizations?limit=100"
        pages = {
            orgs_url: {
                "data": [{"provider": "gh", "remoteIdentifier": "1", "name": "acme"}],
                "pagination": {"cursor": "c2", "limit": 100},
            },
            f"{BASE}/user/organizations?limit=100&cursor=c2": {
                "data": [{"provider": "gl", "remoteIdentifier": "2", "name": "acme-gl"}],
                "pagination": {"limit": 100},
            },
        }
        rows = _collect(monkeypatch, "organizations", pages)
        assert [row["remoteIdentifier"] for row in rows] == ["1", "2"]

    def test_stops_on_empty_page_even_if_cursor_present(self, monkeypatch: Any) -> None:
        # A page with no items but a cursor must terminate, not loop forever.
        pages = {
            f"{BASE}/user/organizations?limit=100": {"data": [], "pagination": {"cursor": "c2", "limit": 100}},
        }
        assert _collect(monkeypatch, "organizations", pages) == []

    def test_page_cap_truncates_fan_out_pagination(self, monkeypatch: Any) -> None:
        files_endpoint = CODACY_ENDPOINTS["files"]
        monkeypatch.setattr(files_endpoint, "max_pages_per_repository", 2)

        files_base = f"{BASE}/organizations/gh/acme/repositories/repo-a/files"
        # Every page advertises another cursor; without the cap this would page forever.
        pages: dict[str, dict[str, Any]] = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            f"{files_base}?limit=100": {"data": [{"path": "a.py"}], "pagination": {"cursor": "c2"}},
            f"{files_base}?limit=100&cursor=c2": {"data": [{"path": "b.py"}], "pagination": {"cursor": "c3"}},
            f"{files_base}?limit=100&cursor=c3": {"data": [{"path": "c.py"}], "pagination": {"cursor": "c4"}},
        }
        logger = MagicMock()

        def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger_: Any) -> dict:
            return pages[url]

        monkeypatch.setattr(codacy, "_fetch_page", fake_fetch)
        rows: list[dict] = []
        for batch in get_rows(api_token="token", provider="gh", organization="acme", endpoint="files", logger=logger):
            rows.extend(batch)

        assert [row["path"] for row in rows] == ["a.py", "b.py"]
        logger.warning.assert_called_once()


class TestFanOut:
    def test_fans_out_over_repositories_and_stamps_repository_onto_rows(self, monkeypatch: Any) -> None:
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}, {"name": "repo-b"}], "pagination": {}},
            f"{BASE}/organizations/gh/acme/repositories/repo-a/files?limit=100": {
                "data": [{"path": "src/main.py", "gradeLetter": "A"}],
                "pagination": {},
            },
            f"{BASE}/organizations/gh/acme/repositories/repo-b/files?limit=100": {
                "data": [{"path": "src/main.py", "gradeLetter": "C"}],
                "pagination": {},
            },
        }
        rows = _collect(monkeypatch, "files", pages)
        # The repository name makes the ["repository", "path"] primary key unique table-wide:
        # both repositories legitimately contain the same path.
        assert rows == [
            {"repository": "repo-a", "path": "src/main.py", "gradeLetter": "A"},
            {"repository": "repo-b", "path": "src/main.py", "gradeLetter": "C"},
        ]

    def test_repository_removed_mid_sync_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}, {"name": "gone"}, {"name": "repo-b"}], "pagination": {}},
            f"{BASE}/organizations/gh/acme/repositories/repo-a/files?limit=100": {
                "data": [{"path": "a.py"}],
                "pagination": {},
            },
            f"{BASE}/organizations/gh/acme/repositories/gone/files?limit=100": not_found,
            f"{BASE}/organizations/gh/acme/repositories/repo-b/files?limit=100": {
                "data": [{"path": "b.py"}],
                "pagination": {},
            },
        }
        rows = _collect(monkeypatch, "files", pages)
        assert [(row["repository"], row["path"]) for row in rows] == [("repo-a", "a.py"), ("repo-b", "b.py")]

    def test_non_404_http_error_propagates(self, monkeypatch: Any) -> None:
        forbidden = requests.HTTPError(response=_response_with_status(403))
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            f"{BASE}/organizations/gh/acme/repositories/repo-a/files?limit=100": forbidden,
        }
        with pytest.raises(requests.HTTPError):
            _collect(monkeypatch, "files", pages)


class TestNormalization:
    def test_repositories_lift_nested_repository_to_top_level(self, monkeypatch: Any) -> None:
        # The ["provider", "owner", "name"] primary key only works if the nested `repository`
        # entity is lifted to top-level columns.
        pages = {
            f"{BASE}/analysis/organizations/gh/acme/repositories?limit=100": {
                "data": [
                    {
                        "repository": {"provider": "gh", "owner": "acme", "name": "repo-a", "repositoryId": 1},
                        "gradeLetter": "B",
                        "issuesCount": 12,
                    }
                ],
                "pagination": {},
            },
        }
        rows = _collect(monkeypatch, "repositories", pages)
        assert rows == [
            {
                "provider": "gh",
                "owner": "acme",
                "name": "repo-a",
                "repositoryId": 1,
                "gradeLetter": "B",
                "issuesCount": 12,
            }
        ]

    def test_pull_requests_lift_nested_pull_request_and_keep_analysis_fields(self, monkeypatch: Any) -> None:
        pr_url = (
            f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/pull-requests?limit=100&includeNotAnalyzed=true"
        )
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            pr_url: {
                "data": [
                    {
                        "pullRequest": {"number": 5, "repository": "repo-a", "updated": "2026-06-02T14:47:46Z"},
                        "isUpToStandards": True,
                        "isAnalysing": False,
                        "newIssues": 2,
                    }
                ],
                "pagination": {},
            },
        }
        rows = _collect(monkeypatch, "pull_requests", pages)
        assert rows == [
            {
                "repository": "repo-a",
                "number": 5,
                "updated": "2026-06-02T14:47:46Z",
                "isUpToStandards": True,
                "isAnalysing": False,
                "newIssues": 2,
            }
        ]

    def test_commits_lift_nested_commit_and_stamp_repository(self, monkeypatch: Any) -> None:
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/commits?limit=100": {
                "data": [
                    {
                        "commit": {"sha": "abc123", "commitTimestamp": "2026-03-25T10:29:59Z"},
                        "quality": {"newIssues": 0},
                    }
                ],
                "pagination": {},
            },
        }
        rows = _collect(monkeypatch, "commits", pages)
        assert rows == [
            {
                "repository": "repo-a",
                "sha": "abc123",
                "commitTimestamp": "2026-03-25T10:29:59Z",
                "quality": {"newIssues": 0},
            }
        ]


class TestFetchPage:
    def _json_response(self, status_code: int, payload: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = payload or {}
        if status_code >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(response=response)
        return response

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("gateway_timeout", 504)])
    def test_transient_statuses_are_retried_until_success(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.side_effect = [
            self._json_response(status_code),
            self._json_response(200, {"data": []}),
        ]
        with patch.object(_fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = _fetch_page(session, "GET", f"{BASE}/user/organizations", {}, MagicMock())
        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_unauthorized_fails_immediately_without_retry(self) -> None:
        # Retrying a bad token can never succeed; it must surface as a hard HTTPError so
        # get_non_retryable_errors can disable the source.
        session = MagicMock()
        session.get.return_value = self._json_response(401)
        with patch.object(_fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.HTTPError):
                _fetch_page(session, "GET", f"{BASE}/user/organizations", {}, MagicMock())
        assert session.get.call_count == 1

    def test_retryable_error_reraised_after_exhausting_attempts(self) -> None:
        session = MagicMock()
        session.get.return_value = self._json_response(503)
        with patch.object(_fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(CodacyRetryableError):
                _fetch_page(session, "GET", f"{BASE}/user/organizations", {}, MagicMock())
        assert session.get.call_count == 5

    def test_issues_search_posts_an_empty_filter_body(self) -> None:
        # searchRepositoryIssues is POST-only; sending a GET (or omitting the JSON body) breaks
        # the one endpoint that isn't a plain GET list.
        session = MagicMock()
        session.post.return_value = self._json_response(200, {"data": []})
        result = _fetch_page(session, "POST", f"{BASE}/analysis/.../issues/search", {}, MagicMock())
        assert result == {"data": []}
        session.post.assert_called_once()
        assert session.post.call_args.kwargs["json"] == {}
        session.get.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand([("valid_token", 200, True), ("invalid_token", 401, False), ("forbidden", 403, False)])
    def test_status_code_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with patch.object(codacy, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is expected

    def test_connection_error_returns_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(codacy, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is False


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_primary_keys_match_endpoint_settings(self, endpoint: str) -> None:
        response = codacy_source(
            api_token="token", provider="gh", organization="acme", endpoint=endpoint, logger=MagicMock()
        )
        assert response.name == endpoint
        assert response.primary_keys == CODACY_ENDPOINTS[endpoint].primary_keys

    def test_fan_out_children_include_repository_in_primary_key(self) -> None:
        # A fan-out child keyed without the repository would multi-match on merge once two
        # repositories share an id (e.g. the same file path), degrading every subsequent sync.
        for endpoint, config in CODACY_ENDPOINTS.items():
            if config.fan_out_per_repository:
                assert config.primary_keys[0] == "repository", endpoint

    def test_commits_partition_on_stable_commit_timestamp(self) -> None:
        response = codacy_source(
            api_token="token", provider="gh", organization="acme", endpoint="commits", logger=MagicMock()
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["commitTimestamp"]
