from datetime import UTC, datetime
from typing import Any

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.codecov import (
    CodecovResumeConfig,
    _ensure_codecov_url,
    _owner_base_url,
    _should_stop_desc,
    parse_repositories,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source import CodecovSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codecov import (
    CodecovSourceConfig,
)

_BASE = "https://api.codecov.io/api/v2/github/acme"


def _driver(repositories: str | None = None) -> SourceDriver:
    config = CodecovSourceConfig(owner_username="acme", api_token="token", repositories=repositories)
    return SourceDriver(CodecovSource(), config)


def _run(
    schema_name: str,
    pages: dict[str, Any],
    *,
    repositories: str | None = None,
    resume_state: CodecovResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        answer = pages[request.url]
        return answer if isinstance(answer, ScriptedResponse) else ScriptedResponse(json=answer)

    return _driver(repositories).run(schema_name, respond, resume_state=resume_state, **inputs)


def _page(results: list[dict], next_url: str | None = None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


_ACTIVE_REPOS_URL = f"{_BASE}/repos?active=true&page_size=500"


class TestParseRepositories:
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", "", []),
            ("single", "repo-one", ["repo-one"]),
            ("comma_separated_with_spaces", " repo-one , repo-two ", ["repo-one", "repo-two"]),
            ("trailing_commas", "repo-one,,", ["repo-one"]),
        ]
    )
    def test_parse(self, _name: str, value: str | None, expected: list[str]) -> None:
        assert parse_repositories(value) == expected


class TestOwnerBaseUrl:
    @parameterized.expand(
        [
            ("plain", "acme", "https://api.codecov.io/api/v2/github/acme"),
            # Path metacharacters must be encoded so a crafted owner can't retarget the
            # request path the bearer token is sent to.
            ("slash", "acme/../evil", "https://api.codecov.io/api/v2/github/acme%2F..%2Fevil"),
            ("query", "acme?x=1", "https://api.codecov.io/api/v2/github/acme%3Fx%3D1"),
        ]
    )
    def test_owner_is_percent_encoded(self, _name: str, owner: str, expected: str) -> None:
        assert _owner_base_url("github", owner) == expected


class TestEnsureCodecovUrl:
    @parameterized.expand(
        [
            ("http_upgraded", "http://api.codecov.io/api/v2/github/acme/repos?page=2"),
            ("https_unchanged", "https://api.codecov.io/api/v2/github/acme/repos?page=2"),
        ]
    )
    def test_valid_urls_normalize_to_https(self, _name: str, url: str) -> None:
        assert _ensure_codecov_url(url) == "https://api.codecov.io/api/v2/github/acme/repos?page=2"

    @parameterized.expand(
        [
            # A pagination link or poisoned resume state pointing anywhere but the Codecov API
            # origin would receive the bearer token — refuse it.
            ("foreign_host", "https://evil.example.com/api/v2/github/acme/repos"),
            ("userinfo_trick", "https://api.codecov.io@evil.example.com/api/v2/repos"),
            ("host_suffix", "https://api.codecov.io.evil.example.com/api/v2/repos"),
            ("path_prefix_escape", "https://api.codecov.io/api/v2evil"),
        ]
    )
    def test_non_codecov_urls_are_refused(self, _name: str, url: str) -> None:
        with pytest.raises(ValueError):
            _ensure_codecov_url(url)


class TestShouldStopDesc:
    _CUTOFF = datetime(2026, 7, 5, tzinfo=UTC)

    @parameterized.expand(
        [
            ("no_cutoff", [{"timestamp": "2026-07-01T00:00:00Z"}], "timestamp", None, False),
            ("all_newer", [{"timestamp": "2026-07-09T00:00:00Z"}], "timestamp", _CUTOFF, False),
            (
                "one_older",
                [{"timestamp": "2026-07-09T00:00:00Z"}, {"timestamp": "2026-07-01T00:00:00Z"}],
                "timestamp",
                _CUTOFF,
                True,
            ),
            ("missing_field", [{"other": "x"}], "timestamp", _CUTOFF, False),
            ("no_field", [{"timestamp": "2026-07-01T00:00:00Z"}], None, _CUTOFF, False),
        ]
    )
    def test_stop(self, _name: str, items: list[dict], field: str | None, cutoff: Any, expected: bool) -> None:
        assert _should_stop_desc(items, field, cutoff) is expected


class TestTopLevelRows:
    def test_repos_paginates_and_upgrades_next_to_https(self) -> None:
        pages = {
            f"{_BASE}/repos?page_size=500": _page(
                [{"name": "r1"}], next_url="http://api.codecov.io/api/v2/github/acme/repos?page=2&page_size=500"
            ),
            # Codecov returns `next` links with an http:// scheme; we must follow them over https.
            "https://api.codecov.io/api/v2/github/acme/repos?page=2&page_size=500": _page([{"name": "r2"}]),
        }
        result = _run("repos", pages)

        assert result.raised is None
        assert [r["name"] for r in result.rows] == ["r1", "r2"]
        assert result.urls == list(pages)
        # State is saved only while more pages remain, and after the page was yielded.
        assert result.saved_states == [
            CodecovResumeConfig(next_url="https://api.codecov.io/api/v2/github/acme/repos?page=2&page_size=500")
        ]

    def test_repos_resumes_from_saved_url(self) -> None:
        resume_url = f"{_BASE}/repos?page=2&page_size=500"
        pages = {resume_url: _page([{"name": "r2"}])}
        result = _run("repos", pages, resume_state=CodecovResumeConfig(next_url=resume_url))

        assert result.raised is None
        assert [r["name"] for r in result.rows] == ["r2"]
        assert result.urls == [resume_url]

    def test_poisoned_next_url_aborts_the_sync(self) -> None:
        pages = {
            f"{_BASE}/repos?page_size=500": _page(
                [{"name": "r1"}], next_url="https://evil.example.com/api/v2/github/acme/repos?page=2"
            ),
        }
        result = _run("repos", pages)

        assert isinstance(result.raised, ValueError)
        assert result.urls == list(pages)

    def test_repos_applies_repository_allow_list(self) -> None:
        pages = {f"{_BASE}/repos?page_size=500": _page([{"name": "r1"}, {"name": "r2"}, {"name": "r3"}])}
        result = _run("repos", pages, repositories="r1, r3")

        assert result.raised is None
        assert [r["name"] for r in result.rows] == ["r1", "r3"]


class TestFanOutRows:
    def test_fans_out_over_active_repos_and_injects_repo(self) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            f"{_BASE}/repos/r1/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 90.0}]),
            f"{_BASE}/repos/r2/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 80.0}]),
        }
        result = _run("flags", pages)

        assert result.raised is None
        assert [(r["repo"], r["flag_name"]) for r in result.rows] == [("r1", "unit"), ("r2", "unit")]
        assert result.urls == list(pages)
        # The bookmark advances to the next repo so a crash between repos resumes correctly.
        assert result.saved_states == [CodecovResumeConfig(next_url=None, repo="r2")]

    def test_resumes_from_bookmarked_repo_and_url(self) -> None:
        resume_url = f"{_BASE}/repos/r2/flags?page=2&page_size=500"
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}, {"name": "r3"}]),
            resume_url: _page([{"flag_name": "unit", "coverage": 80.0}]),
            f"{_BASE}/repos/r3/flags?page_size=500": _page([{"flag_name": "unit", "coverage": 60.0}]),
        }
        result = _run("flags", pages, resume_state=CodecovResumeConfig(next_url=resume_url, repo="r2"))

        # r1 was already synced; r2 resumes mid-pagination, r3 starts from its first page.
        assert result.raised is None
        assert [r["repo"] for r in result.rows] == ["r2", "r3"]
        assert result.urls == list(pages)
        assert f"{_BASE}/repos/r1/flags?page_size=500" not in result.urls

    def test_components_bare_list_endpoint(self) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/components": [{"component_id": "api", "name": "api", "coverage": 91.2}],
        }
        result = _run("components", pages)

        assert result.raised is None
        assert result.rows == [{"component_id": "api", "name": "api", "coverage": 91.2, "repo": "r1"}]
        assert result.urls == list(pages)


class TestCoverageReportEndpoints:
    def test_repo_without_a_coverage_report_yields_nothing(self) -> None:
        # Codecov 404s a repo that has never had a report processed; the fan-out skips it.
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            f"{_BASE}/repos/r1/totals": ScriptedResponse(status=404),
            f"{_BASE}/repos/r2/totals": {"totals": {"coverage": 80.0}, "files": [], "commit_file_url": None},
        }
        result = _run("repo_totals", pages)

        assert result.raised is None
        assert [r["repo"] for r in result.rows] == ["r2"]
        assert result.urls == list(pages)

    def test_report_files_yields_one_row_per_file(self) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/report": {
                "totals": {"coverage": 90.0},
                "files": [
                    {"name": "app.py", "totals": {"lines": 2}, "line_coverage": [[1, 0], [2, 1]]},
                    {"name": "lib/util.py", "totals": {"lines": 1}, "line_coverage": [[7, 2]]},
                ],
                "commit_file_url": "https://app.codecov.io/gh/acme/r1",
            },
        }
        result = _run("report_files", pages)

        assert result.raised is None
        assert [(r["repo"], r["name"]) for r in result.rows] == [("r1", "app.py"), ("r1", "lib/util.py")]
        assert result.rows[0]["line_coverage"] == [[1, 0], [2, 1]]
        assert result.urls == list(pages)

    def test_report_tree_flattens_every_nesting_level(self) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/report/tree?depth=100": [
                {
                    "name": "foo",
                    "full_path": "foo",
                    "coverage": 62.5,
                    "lines": 8,
                    "hits": 5,
                    "partials": 0,
                    "misses": 3,
                    "children": [
                        {
                            "name": "bar",
                            "full_path": "foo/bar",
                            "coverage": 50.0,
                            "lines": 4,
                            "hits": 2,
                            "partials": 0,
                            "misses": 2,
                            "children": [
                                {
                                    "name": "file1.py",
                                    "full_path": "foo/bar/file1.py",
                                    "coverage": 50.0,
                                    "lines": 4,
                                    "hits": 2,
                                    "partials": 0,
                                    "misses": 2,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "file2.py",
                    "full_path": "file2.py",
                    "coverage": 100.0,
                    "lines": 1,
                    "hits": 1,
                    "partials": 0,
                    "misses": 0,
                },
            ],
        }
        result = _run("report_tree", pages)

        # Directories and files become sibling rows keyed by full_path, and `children` is
        # dropped rather than stored as a nested column.
        assert result.raised is None
        assert [r["full_path"] for r in result.rows] == ["foo", "foo/bar", "foo/bar/file1.py", "file2.py"]
        assert all(r["repo"] == "r1" for r in result.rows)
        assert not any("children" in r for r in result.rows)
        assert result.urls == list(pages)


class TestParentFanOut:
    @parameterized.expand(
        [
            (
                # The flag name is a path segment, so it is percent-encoded.
                "flag_coverage_trend",
                f"{_BASE}/repos/r1/flags?page_size=500",
                [{"flag_name": "unit/py", "coverage": 90.0}],
                f"{_BASE}/repos/r1/flags/unit%2Fpy/coverage?page_size=500&interval=1d",
                _page([{"timestamp": "2026-07-06T00:00:00Z", "min": 90.0, "max": 91.0, "avg": 90.5}]),
                [
                    {
                        "timestamp": "2026-07-06T00:00:00Z",
                        "min": 90.0,
                        "max": 91.0,
                        "avg": 90.5,
                        "flag_name": "unit/py",
                        "repo": "r1",
                    }
                ],
            ),
            (
                "pull_impacted_files",
                f"{_BASE}/repos/r1/pulls?page_size=500",
                [{"pullid": 7, "updatestamp": "2026-07-06T00:00:00Z"}],
                f"{_BASE}/repos/r1/compare/impacted_files?pullid=7",
                {
                    "base_commit": "aaa",
                    "head_commit": "bbb",
                    "state": "processed",
                    "totals": {"base": {}, "head": {}},
                    "commit_uploads": [{"commitid": "bbb"}],
                    "diff": {"git_commits": []},
                    "untracked": [],
                    "files": [{"file_name": "app.py", "change_coverage": 5.0}],
                },
                [
                    {
                        "file_name": "app.py",
                        "change_coverage": 5.0,
                        "base_commit": "aaa",
                        "head_commit": "bbb",
                        "state": "processed",
                        "repo": "r1",
                        "pullid": 7,
                        "pull_updatestamp": "2026-07-06T00:00:00Z",
                    }
                ],
            ),
            (
                # Codecov is still computing the comparison, so there are no file rows yet.
                "pull_impacted_files_pending",
                f"{_BASE}/repos/r1/pulls?page_size=500",
                [{"pullid": 7, "updatestamp": "2026-07-06T00:00:00Z"}],
                f"{_BASE}/repos/r1/compare/impacted_files?pullid=7",
                {"base_commit": "aaa", "head_commit": "bbb", "state": "pending", "files": []},
                [],
            ),
            (
                "pull_component_comparisons",
                f"{_BASE}/repos/r1/pulls?page_size=500",
                [{"pullid": 7, "updatestamp": None}],
                f"{_BASE}/repos/r1/compare/components?pullid=7",
                [{"component_id": "api", "name": "api", "diff_totals": {"coverage": 80.0}}],
                [
                    {
                        "component_id": "api",
                        "name": "api",
                        "diff_totals": {"coverage": 80.0},
                        "repo": "r1",
                        "pullid": 7,
                        "pull_updatestamp": None,
                    }
                ],
            ),
        ]
    )
    def test_child_rows_carry_parent_columns(
        self,
        name: str,
        parent_url: str,
        parents: list[dict],
        child_url: str,
        child_response: Any,
        expected_rows: list[dict],
    ) -> None:
        schema_name = name.removesuffix("_pending")
        pages = {_ACTIVE_REPOS_URL: _page([{"name": "r1"}]), parent_url: _page(parents), child_url: child_response}
        result = _run(schema_name, pages)

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.urls == list(pages)

    def test_walks_parent_pages_and_skips_children_that_404(self) -> None:
        commits_page_2 = f"{_BASE}/repos/r1/commits?page=2&page_size=500"
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            f"{_BASE}/repos/r1/commits?page_size=500": _page(
                [{"commitid": "c1", "timestamp": "2026-07-09T00:00:00Z"}], next_url=commits_page_2
            ),
            # A commit without uploads (or deleted since the listing) is skipped, not fatal.
            f"{_BASE}/repos/r1/commits/c1/uploads?page_size=500": ScriptedResponse(status=404),
            commits_page_2: _page([{"commitid": "c2", "timestamp": "2026-07-08T00:00:00Z"}]),
            f"{_BASE}/repos/r1/commits/c2/uploads?page_size=500": _page(
                [{"created_at": "2026-07-08T00:01:00Z", "storage_path": "v4/raw/c2/u1.txt", "state": "processed"}]
            ),
            # A repo whose commit list 404s (deleted since enumeration) is skipped too.
            f"{_BASE}/repos/r2/commits?page_size=500": ScriptedResponse(status=404),
        }
        result = _run("commit_uploads", pages)

        assert result.raised is None
        assert [(r["repo"], r["commitid"], r["commit_timestamp"], r["storage_path"]) for r in result.rows] == [
            ("r1", "c2", "2026-07-08T00:00:00Z", "v4/raw/c2/u1.txt")
        ]
        assert result.urls == list(pages)
        # The cursor moves to the next parent page, then to the next repo, once every child row
        # before it has been yielded.
        assert result.saved_states == [
            CodecovResumeConfig(next_url=commits_page_2, repo="r1"),
            CodecovResumeConfig(next_url=None, repo="r2"),
        ]

    def test_resumes_from_saved_parent_page(self) -> None:
        resume_url = f"{_BASE}/repos/r2/flags?page=2&page_size=500"
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            resume_url: _page([{"flag_name": "e2e"}]),
            f"{_BASE}/repos/r2/flags/e2e/coverage?page_size=500&interval=1d": _page(
                [{"timestamp": "2026-07-06T00:00:00Z", "min": 1.0, "max": 1.0, "avg": 1.0}]
            ),
        }
        result = _run("flag_coverage_trend", pages, resume_state=CodecovResumeConfig(next_url=resume_url, repo="r2"))

        assert result.raised is None
        assert [(r["repo"], r["flag_name"]) for r in result.rows] == [("r2", "e2e")]
        assert result.urls == list(pages)


class TestIncrementalSync:
    _WATERMARK = datetime(2026, 7, 5, tzinfo=UTC)

    def test_commits_stop_paging_at_watermark_but_continue_to_next_repo(self) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}, {"name": "r2"}]),
            f"{_BASE}/repos/r1/commits?page_size=500": _page(
                [
                    {"commitid": "new", "timestamp": "2026-07-09T00:00:00Z"},
                    {"commitid": "old", "timestamp": "2026-07-01T00:00:00Z"},
                ],
                next_url=f"{_BASE}/repos/r1/commits?page=2&page_size=500",
            ),
            f"{_BASE}/repos/r2/commits?page_size=500": _page(
                [{"commitid": "other", "timestamp": "2026-07-08T00:00:00Z"}]
            ),
        }
        result = _run(
            "commits",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._WATERMARK,
        )

        # The boundary page is yielded in full (merge dedupes), then pagination stops for r1
        # while r2 still syncs.
        assert result.raised is None
        assert [r["commitid"] for r in result.rows] == ["new", "old", "other"]
        assert result.urls == list(pages)
        assert f"{_BASE}/repos/r1/commits?page=2&page_size=500" not in result.urls
        # No page checkpoint is saved on a stopping page — only the repo bookmark.
        assert result.saved_states == [CodecovResumeConfig(next_url=None, repo="r2")]

    def test_commits_without_watermark_page_through_everything(self) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/commits?page_size=500": _page(
                [{"commitid": "a", "timestamp": "2026-07-09T00:00:00Z"}],
                next_url=f"{_BASE}/repos/r1/commits?page=2&page_size=500",
            ),
            f"{_BASE}/repos/r1/commits?page=2&page_size=500": _page(
                [{"commitid": "b", "timestamp": "2020-01-01T00:00:00Z"}]
            ),
        }
        result = _run(
            "commits",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert [r["commitid"] for r in result.rows] == ["a", "b"]
        assert result.urls == list(pages)

    def test_coverage_trend_uses_server_side_start_date(self) -> None:
        pages = {
            _ACTIVE_REPOS_URL: _page([{"name": "r1"}]),
            f"{_BASE}/repos/r1/coverage?page_size=500&interval=1d&start_date=2026-07-05": _page(
                [{"timestamp": "2026-07-06T00:00:00Z", "min": 90.0, "max": 91.0, "avg": 90.5}]
            ),
        }
        result = _run(
            "coverage_trend",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._WATERMARK,
        )

        assert result.raised is None
        assert [r["repo"] for r in result.rows] == ["r1"]
        assert result.urls == list(pages)
        assert result.requests[-1].param("start_date") == "2026-07-05"

    @parameterized.expand(
        [
            (
                # The pulls list filters on `updatestamp` server-side.
                "pull_flag_comparisons",
                {
                    f"{_BASE}/repos/r1/pulls?page_size=500&start_date=2026-07-05": _page(
                        [{"pullid": 7, "updatestamp": "2026-07-06T00:00:00Z"}]
                    ),
                    f"{_BASE}/repos/r1/compare/flags?pullid=7": [{"name": "unit", "diff_totals": None}],
                },
            ),
            (
                # Each flag's coverage series takes the same `start_date` as coverage_trend.
                "flag_coverage_trend",
                {
                    f"{_BASE}/repos/r1/flags?page_size=500": _page([{"flag_name": "unit"}]),
                    f"{_BASE}/repos/r1/flags/unit/coverage?page_size=500&interval=1d&start_date=2026-07-05": _page(
                        [{"timestamp": "2026-07-06T00:00:00Z", "min": 1.0, "max": 1.0, "avg": 1.0}]
                    ),
                },
            ),
            (
                # Uploads have no filter, so paging the newest-first commits stops at the
                # watermark; page 2 is never requested.
                "commit_uploads",
                {
                    f"{_BASE}/repos/r1/commits?page_size=500": _page(
                        [
                            {"commitid": "new", "timestamp": "2026-07-09T00:00:00Z"},
                            {"commitid": "old", "timestamp": "2026-07-01T00:00:00Z"},
                        ],
                        next_url=f"{_BASE}/repos/r1/commits?page=2&page_size=500",
                    ),
                    f"{_BASE}/repos/r1/commits/new/uploads?page_size=500": _page(
                        [{"created_at": "2026-07-09T00:01:00Z", "storage_path": "a"}]
                    ),
                    f"{_BASE}/repos/r1/commits/old/uploads?page_size=500": _page(
                        [{"created_at": "2026-07-01T00:01:00Z", "storage_path": "b"}]
                    ),
                },
            ),
        ]
    )
    def test_parent_fan_out_incremental_request_shaping(self, schema_name: str, endpoint_pages: dict[str, Any]) -> None:
        pages = {_ACTIVE_REPOS_URL: _page([{"name": "r1"}]), **endpoint_pages}
        result = _run(
            schema_name,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self._WATERMARK,
        )

        assert result.raised is None
        assert result.rows
        assert result.urls == list(pages)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("unknown_owner", 404, (False, 404)),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: tuple) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("token", "github", "acme") == expected
        assert [request.url for request in network.requests_log] == [f"{_BASE}/repos?page_size=1"]
        assert network.requests_log[0].headers["authorization"] == "bearer token"

    def test_transport_error_maps_to_none(self) -> None:
        with scripted_network([requests.ConnectionError("boom")]) as network:
            assert validate_credentials("token", "github", "acme") == (False, None)
        assert network.requests_log
        assert {request.url for request in network.requests_log} == {f"{_BASE}/repos?page_size=1"}
