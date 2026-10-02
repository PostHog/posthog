from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.settings import (
    CODACY_ENDPOINTS,
    COMMIT_STATISTICS_DAYS,
    ENDPOINTS,
    METRICS_LOOKBACK_DAYS,
    METRICS_PERIOD,
)

BASE = "https://api.codacy.com/api/v3"
REPOS_URL = f"{BASE}/organizations/gh/acme/repositories?limit=100"


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


def _collect(monkeypatch: Any, endpoint: str, pages: dict[str, Any]) -> list[dict]:
    """Run get_rows against URL-keyed fixtures; a request for an unexpected URL fails loudly."""

    def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger: Any, body: Any = None) -> dict:
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
        monkeypatch.setitem(CODACY_ENDPOINTS, "files", replace(files_endpoint, max_pages_per_parent=2))

        files_base = f"{BASE}/organizations/gh/acme/repositories/repo-a/files"
        # Every page advertises another cursor; without the cap this would page forever.
        pages: dict[str, dict[str, Any]] = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            f"{files_base}?limit=100": {"data": [{"path": "a.py"}], "pagination": {"cursor": "c2"}},
            f"{files_base}?limit=100&cursor=c2": {"data": [{"path": "b.py"}], "pagination": {"cursor": "c3"}},
            f"{files_base}?limit=100&cursor=c3": {"data": [{"path": "c.py"}], "pagination": {"cursor": "c4"}},
        }
        logger = MagicMock()

        def fake_fetch(
            session: Any, method: str, url: str, headers: dict[str, str], logger_: Any, body: Any = None
        ) -> dict:
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

    def test_post_body_is_forwarded(self) -> None:
        # The metrics time series rejects an empty body; it carries the required date range.
        session = MagicMock()
        session.post.return_value = self._json_response(200, {"data": []})
        body = {"from": "2026-01-01", "to": "2026-12-31"}
        _fetch_page(session, "POST", f"{BASE}/organizations/gh/acme/metrics/x/timerange", {}, MagicMock(), body)
        assert session.post.call_args.kwargs["json"] == body


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
            if config.fan_out in ("repository", "commit", "pull_request"):
                assert config.primary_keys[0] == "repository", endpoint

    def test_commits_partition_on_stable_commit_timestamp(self) -> None:
        response = codacy_source(
            api_token="token", provider="gh", organization="acme", endpoint="commits", logger=MagicMock()
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["commitTimestamp"]


class TestToolFanOut:
    def test_patterns_are_stamped_with_their_tool_uuid(self, monkeypatch: Any) -> None:
        # Codacy documents pattern ids as unique per tool only, so without the tool uuid the
        # ["toolUuid", "id"] key collapses and two tools sharing an id multi-match on merge.
        pages = {
            f"{BASE}/tools?limit=100": {
                "data": [{"uuid": "uuid-1", "name": "ESLint"}, {"uuid": "uuid-2", "name": "PMD"}],
                "pagination": {},
            },
            f"{BASE}/tools/uuid-1/patterns?limit=100": {
                "data": [{"id": "unused", "category": "ErrorProne"}],
                "pagination": {},
            },
            f"{BASE}/tools/uuid-2/patterns?limit=100": {
                "data": [{"id": "unused", "category": "CodeStyle"}],
                "pagination": {},
            },
        }
        rows = _collect(monkeypatch, "tool_patterns", pages)
        assert rows == [
            {"toolUuid": "uuid-1", "id": "unused", "category": "ErrorProne"},
            {"toolUuid": "uuid-2", "id": "unused", "category": "CodeStyle"},
        ]

    def test_tools_without_a_uuid_are_not_fanned_out(self, monkeypatch: Any) -> None:
        # A uuid-less entry would format into /tools/None/patterns and 404 the whole sweep.
        pages = {
            f"{BASE}/tools?limit=100": {"data": [{"name": "Broken"}], "pagination": {}},
        }
        assert _collect(monkeypatch, "tool_patterns", pages) == []


class TestCommitFanOut:
    def _commit_pages(self, shas: list[str]) -> dict[str, Any]:
        return {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/commits?limit=100": {
                "data": [{"commit": {"sha": sha}} for sha in shas],
                "pagination": {},
            },
        }

    def _delta_url(self, sha: str) -> str:
        return f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/commits/{sha}/deltaIssues?limit=100"

    def test_lifts_commit_issue_and_stamps_repository_and_commit(self, monkeypatch: Any) -> None:
        pages = self._commit_pages(["sha1"])
        pages[self._delta_url("sha1")] = {
            "data": [{"commitIssue": {"resultDataId": 7, "message": "unused import"}, "deltaType": "Added"}],
            "pagination": {},
        }
        rows = _collect(monkeypatch, "commit_delta_issues", pages)
        # resultDataId is only stable within a repository, and the same issue can be added by one
        # commit and fixed by another, so both parents have to reach the row as columns.
        assert rows == [
            {
                "repository": "repo-a",
                "commitSha": "sha1",
                "resultDataId": 7,
                "message": "unused import",
                "deltaType": "Added",
            }
        ]

    def test_commit_cap_bounds_the_per_commit_request_fan_out(self, monkeypatch: Any) -> None:
        # deltaIssues costs one request per commit, so an uncapped walk over a busy repository
        # would never finish inside Codacy's rate limit.
        endpoint = CODACY_ENDPOINTS["commit_delta_issues"]
        monkeypatch.setitem(
            CODACY_ENDPOINTS,
            "commit_delta_issues",
            replace(endpoint, max_commits_per_repository=2),
        )

        pages = self._commit_pages(["sha1", "sha2", "sha3"])
        for sha in ("sha1", "sha2", "sha3"):
            pages[self._delta_url(sha)] = {"data": [{"commitIssue": {"resultDataId": 1}}], "pagination": {}}

        logger = MagicMock()

        def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger_: Any, body: Any = None):
            return pages[url]

        monkeypatch.setattr(codacy, "_fetch_page", fake_fetch)
        rows: list[dict] = []
        for batch in get_rows(
            api_token="token", provider="gh", organization="acme", endpoint="commit_delta_issues", logger=logger
        ):
            rows.extend(batch)

        assert [row["commitSha"] for row in rows] == ["sha1", "sha2"]
        logger.warning.assert_called_once()

    def test_commit_removed_mid_sync_is_skipped_without_losing_the_repository(self, monkeypatch: Any) -> None:
        pages = self._commit_pages(["sha1", "gone", "sha2"])
        pages[self._delta_url("sha1")] = {"data": [{"commitIssue": {"resultDataId": 1}}], "pagination": {}}
        pages[self._delta_url("gone")] = requests.HTTPError(response=_response_with_status(404))
        pages[self._delta_url("sha2")] = {"data": [{"commitIssue": {"resultDataId": 2}}], "pagination": {}}

        rows = _collect(monkeypatch, "commit_delta_issues", pages)
        assert [row["commitSha"] for row in rows] == ["sha1", "sha2"]


class TestMetricsFanOut:
    READY_URL = f"{BASE}/organizations/gh/acme/metrics/ready"

    def _timerange_url(self, metric: str) -> str:
        return f"{BASE}/organizations/gh/acme/metrics/{metric}/timerange?limit=100"

    def _run(self, monkeypatch: Any, pages: dict[str, Any]) -> tuple[list[dict], list[dict]]:
        bodies: list[dict] = []

        def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger_: Any, body: Any = None):
            if body is not None:
                bodies.append(body)
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(codacy, "_fetch_page", fake_fetch)
        rows: list[dict] = []
        for batch in get_rows(
            api_token="token", provider="gh", organization="acme", endpoint="metrics_timerange", logger=MagicMock()
        ):
            rows.extend(batch)
        return rows, bodies

    def test_flattens_group_and_stamps_metric_name(self, monkeypatch: Any) -> None:
        pages = {
            self.READY_URL: {"data": {"readyMetrics": ["openissues"]}},
            self._timerange_url("openissues"): {
                "data": [
                    {
                        "date": "2026-09-01",
                        "group": {"organization": "acme", "repository": "repo-a", "dimensions": ["Security"]},
                        "value": 12.0,
                        "latestValue": 11.0,
                    }
                ]
            },
        }
        rows, _ = self._run(monkeypatch, pages)
        assert rows == [
            {
                "metricName": "openissues",
                "organization": "acme",
                "repository": "repo-a",
                "dimensions": ["Security"],
                "date": "2026-09-01",
                "value": 12.0,
                "latestValue": 11.0,
            }
        ]

    def test_ungrouped_value_keys_on_an_empty_repository(self, monkeypatch: Any) -> None:
        # repository is part of the primary key; a null there never matches on merge, so the
        # row would be re-inserted on every sync.
        pages = {
            self.READY_URL: {"data": {"readyMetrics": ["openissues"]}},
            self._timerange_url("openissues"): {"data": [{"date": "2026-09-01", "value": 3.0}]},
        }
        rows, _ = self._run(monkeypatch, pages)
        assert rows[0]["repository"] == ""

    def test_request_body_carries_the_required_range_and_grouping(self, monkeypatch: Any) -> None:
        # The endpoint rejects a body without from/to/groupBy, and the same window has to be
        # reused for every metric so one table holds a consistent range.
        pages = {
            self.READY_URL: {"data": {"readyMetrics": ["openissues", "newissues"]}},
            self._timerange_url("openissues"): {"data": []},
            self._timerange_url("newissues"): {"data": []},
        }
        _, bodies = self._run(monkeypatch, pages)
        assert len(bodies) == 2
        assert bodies[0] == bodies[1]
        today = datetime.now(UTC).date()
        assert bodies[0] == {
            "filter": {"entityFilter": {}},
            "groupBy": {"groupBy": ["repository"]},
            "from": (today - timedelta(days=METRICS_LOOKBACK_DAYS)).isoformat(),
            "to": today.isoformat(),
            "period": METRICS_PERIOD,
        }

    @parameterized.expand([("not_entitled", 403), ("not_found", 404)])
    def test_organization_without_metrics_syncs_empty(self, _name: str, status_code: int) -> None:
        # Metrics are opt-in on Codacy; the table has to come back empty rather than failing
        # the schema for every account that hasn't enabled them.
        def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger_: Any, body: Any = None):
            raise requests.HTTPError(response=_response_with_status(status_code))

        with patch.object(codacy, "_fetch_page", fake_fetch):
            rows = list(
                get_rows(
                    api_token="token",
                    provider="gh",
                    organization="acme",
                    endpoint="metrics_timerange",
                    logger=MagicMock(),
                )
            )
        assert rows == []

    def test_unexpected_error_on_ready_metrics_propagates(self) -> None:
        def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger_: Any, body: Any = None):
            raise requests.HTTPError(response=_response_with_status(400))

        with patch.object(codacy, "_fetch_page", fake_fetch):
            with pytest.raises(requests.HTTPError):
                list(
                    get_rows(
                        api_token="token",
                        provider="gh",
                        organization="acme",
                        endpoint="metrics_timerange",
                        logger=MagicMock(),
                    )
                )


class TestSingleResponseEndpoints:
    """Endpoints that answer with one complete payload and declare no `cursor` or `limit`."""

    def _urls(self, monkeypatch: Any, endpoint: str, pages: dict[str, Any]) -> tuple[list[dict], list[str]]:
        requested: list[str] = []

        def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger_: Any, body: Any = None):
            requested.append(url)
            return pages[url]

        monkeypatch.setattr(codacy, "_fetch_page", fake_fetch)
        rows: list[dict] = []
        for batch in get_rows(
            api_token="token", provider="gh", organization="acme", endpoint=endpoint, logger=MagicMock()
        ):
            rows.extend(batch)
        return rows, requested

    def test_commit_statistics_requests_the_day_range_without_pagination_params(self, monkeypatch: Any) -> None:
        # The endpoint declares only `days`; sending the `limit` every paginated endpoint carries
        # makes Codacy reject the request, so the whole table would fail to sync.
        stats_url = (
            f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/commit-statistics?days={COMMIT_STATISTICS_DAYS}"
        )
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            stats_url: {"data": [{"commitId": 1, "commitTimestamp": "2026-04-01T09:00:00Z", "numberIssues": 4}]},
        }
        rows, requested = self._urls(monkeypatch, "commit_statistics", pages)
        assert stats_url in requested
        assert rows == [
            {"repository": "repo-a", "commitId": 1, "commitTimestamp": "2026-04-01T09:00:00Z", "numberIssues": 4}
        ]

    def test_category_overviews_flatten_the_nested_category(self, monkeypatch: Any) -> None:
        # categoryName is half of the primary key, so it has to be a plain top-level column.
        overviews_url = f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/category-overviews"
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            overviews_url: {
                "data": [
                    {
                        "commitId": 9,
                        "category": {"name": "Security", "categoryType": "Security", "description": "Security issues"},
                        "percentage": 1.6,
                        "totalResults": 3,
                    }
                ]
            },
        }
        rows, _ = self._urls(monkeypatch, "category_overviews", pages)
        assert rows == [
            {
                "repository": "repo-a",
                "categoryName": "Security",
                "categoryType": "Security",
                "categoryDescription": "Security issues",
                "commitId": 9,
                "percentage": 1.6,
                "totalResults": 3,
            }
        ]

    def test_issues_overview_unnests_every_count_breakdown(self, monkeypatch: Any) -> None:
        # The response is one object of parallel count arrays; left nested the table could not be
        # grouped by dimension, which is the only thing these counts are for.
        overview_url = f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/issues/overview"
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            overview_url: {
                "data": {
                    "counts": {
                        "categories": [{"name": "Security", "total": 3}],
                        "levels": [{"name": "Error", "total": 2}, {"name": "Warning", "total": 1}],
                        "patterns": [{"id": "ESLint_no-unused-vars", "title": "No unused vars", "total": 5}],
                    }
                }
            },
        }
        rows, _ = self._urls(monkeypatch, "issues_overview", pages)
        assert rows == [
            {"repository": "repo-a", "dimension": "categories", "name": "Security", "total": 3, "title": None},
            {"repository": "repo-a", "dimension": "levels", "name": "Error", "total": 2, "title": None},
            {"repository": "repo-a", "dimension": "levels", "name": "Warning", "total": 1, "title": None},
            {
                "repository": "repo-a",
                "dimension": "patterns",
                # The patterns breakdown has no `name`; the pattern id is what identifies the row.
                "name": "ESLint_no-unused-vars",
                "total": 5,
                "title": "No unused vars",
            },
        ]

    def test_repository_without_issues_yields_no_overview_rows(self, monkeypatch: Any) -> None:
        overview_url = f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/issues/overview"
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            overview_url: {"data": {"counts": {"categories": [], "levels": []}}},
        }
        rows, _ = self._urls(monkeypatch, "issues_overview", pages)
        assert rows == []


class TestSecurityItems:
    def test_paginates_in_detection_order(self, monkeypatch: Any) -> None:
        # The endpoint defaults to due date descending, which reshuffles as items are triaged and
        # can skip or repeat rows across page boundaries.
        search = f"{BASE}/organizations/gh/acme/security/items/search"
        pages = {
            f"{search}?limit=100&sort=DetectedAt&direction=asc": {
                "data": [{"id": "item-1", "openedAt": "2026-01-02T00:00:00Z", "priority": "Critical"}],
                "pagination": {"cursor": "c2"},
            },
            f"{search}?limit=100&sort=DetectedAt&direction=asc&cursor=c2": {
                "data": [{"id": "item-2", "openedAt": "2026-01-03T00:00:00Z", "priority": "Low"}],
                "pagination": {},
            },
        }
        rows = _collect(monkeypatch, "security_items", pages)
        assert [row["id"] for row in rows] == ["item-1", "item-2"]

    @parameterized.expand([("security_items", False), ("organizations", True)])
    def test_sample_capture_is_off_for_security_findings(self, endpoint: str, expected: bool) -> None:
        # Security rows carry free-text finding bodies and secret-scan detail that the capture
        # pipeline's name-based scrubber cannot recognise, so they must stay out of the samples.
        with patch.object(codacy, "make_tracked_session") as make_session:
            with patch.object(codacy, "_fetch_page", return_value={"data": []}):
                list(
                    get_rows(
                        api_token="token",
                        provider="gh",
                        organization="acme",
                        endpoint=endpoint,
                        logger=MagicMock(),
                    )
                )
        assert make_session.call_args.kwargs["capture"] is expected

    def test_partitions_on_the_stable_detection_timestamp(self) -> None:
        # dueAt and closedAt both move as an item is triaged, so partitioning on either would
        # rewrite partitions on every sync.
        response = codacy_source(
            api_token="token", provider="gh", organization="acme", endpoint="security_items", logger=MagicMock()
        )
        assert response.partition_keys == ["openedAt"]


class TestPullRequestFanOut:
    COVERAGE_BASE = f"{BASE}/coverage/organizations/gh/acme/repositories/repo-a/pull-requests"
    # No includeNotAnalyzed: coverage only exists for pull requests Codacy analysed.
    PRS_URL = f"{BASE}/analysis/organizations/gh/acme/repositories/repo-a/pull-requests?limit=100"

    def _run(self, monkeypatch: Any, endpoint: str, pages: dict[str, Any], logger: Any = None) -> list[dict]:
        def fake_fetch(session: Any, method: str, url: str, headers: dict[str, str], logger_: Any, body: Any = None):
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(codacy, "_fetch_page", fake_fetch)
        rows: list[dict] = []
        for batch in get_rows(
            api_token="token",
            provider="gh",
            organization="acme",
            endpoint=endpoint,
            logger=logger or MagicMock(),
        ):
            rows.extend(batch)
        return rows

    def test_coverage_row_merges_the_pull_request_and_its_coverage(self, monkeypatch: Any) -> None:
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            self.PRS_URL: {"data": [{"pullRequest": {"number": 7}}], "pagination": {}},
            f"{self.COVERAGE_BASE}/7": {
                "data": {
                    "pullRequest": {"id": 1, "number": 7, "status": "open", "targetBranch": "master"},
                    "coverage": {"deltaCoverage": -1.5, "isUpToStandards": False},
                }
            },
        }
        rows = self._run(monkeypatch, "pull_request_coverage", pages)
        assert rows == [
            {
                "repository": "repo-a",
                "pullRequestNumber": 7,
                "id": 1,
                "number": 7,
                "status": "open",
                "targetBranch": "master",
                "deltaCoverage": -1.5,
                "isUpToStandards": False,
            }
        ]

    def test_file_coverage_rows_carry_both_parents(self, monkeypatch: Any) -> None:
        # A file path repeats across pull requests and repositories, so neither parent can be
        # dropped from the ["repository", "pullRequestNumber", "fileName"] key.
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            self.PRS_URL: {"data": [{"pullRequest": {"number": 7}}], "pagination": {}},
            f"{self.COVERAGE_BASE}/7/files": {
                "data": [{"fileName": "src/main.py", "coverage": 82.0, "variation": -3.0}]
            },
        }
        rows = self._run(monkeypatch, "pull_request_file_coverage", pages)
        assert rows == [
            {
                "repository": "repo-a",
                "pullRequestNumber": 7,
                "fileName": "src/main.py",
                "coverage": 82.0,
                "variation": -3.0,
            }
        ]

    def test_pull_request_cap_bounds_the_per_pull_request_request_fan_out(self, monkeypatch: Any) -> None:
        # Coverage costs a request per pull request, so an uncapped walk over a busy repository
        # would never finish inside Codacy's rate limit.
        endpoint = CODACY_ENDPOINTS["pull_request_coverage"]
        monkeypatch.setitem(
            CODACY_ENDPOINTS,
            "pull_request_coverage",
            replace(endpoint, max_pull_requests_per_repository=2),
        )

        pages: dict[str, Any] = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            self.PRS_URL: {"data": [{"pullRequest": {"number": n}} for n in (7, 8, 9)], "pagination": {}},
        }
        for number in (7, 8, 9):
            pages[f"{self.COVERAGE_BASE}/{number}"] = {"data": {"pullRequest": {"number": number}, "coverage": {}}}

        logger = MagicMock()
        rows = self._run(monkeypatch, "pull_request_coverage", pages, logger)
        assert [row["pullRequestNumber"] for row in rows] == [7, 8]
        logger.warning.assert_called_once()

    def test_pull_request_without_coverage_is_skipped(self, monkeypatch: Any) -> None:
        # A pull request analysed with no coverage report uploaded answers 404; it must not fail
        # the whole repository sweep.
        pages: dict[str, Any] = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            self.PRS_URL: {"data": [{"pullRequest": {"number": n}} for n in (7, 8)], "pagination": {}},
            f"{self.COVERAGE_BASE}/7": requests.HTTPError(response=_response_with_status(404)),
            f"{self.COVERAGE_BASE}/8": {"data": {"pullRequest": {"number": 8}, "coverage": {"deltaCoverage": 0.0}}},
        }
        rows = self._run(monkeypatch, "pull_request_coverage", pages)
        assert [row["pullRequestNumber"] for row in rows] == [8]

    def test_pull_request_without_a_number_is_not_fanned_out(self, monkeypatch: Any) -> None:
        # A number-less entry would format into /pull-requests/None and 404 the whole sweep.
        pages = {
            REPOS_URL: {"data": [{"name": "repo-a"}], "pagination": {}},
            self.PRS_URL: {"data": [{"pullRequest": {}}], "pagination": {}},
        }
        assert self._run(monkeypatch, "pull_request_coverage", pages) == []
