from datetime import UTC, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.coveralls import (
    MAX_REPOSITORIES,
    CoverallsResumeConfig,
    CoverallsRetryableError,
    _builds_url,
    _incremental_cutoff,
    parse_repositories,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.settings import COVERALLS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source import CoverallsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coveralls import (
    CoverallsSourceConfig,
)


def _driver(repositories: str = "acme/widgets", api_token: str | None = None) -> SourceDriver:
    return SourceDriver(
        CoverallsSource(), CoverallsSourceConfig(repositories=repositories, service="github", api_token=api_token)
    )


def _build(build_id: int, created_at: str, repo_name: str | None = "acme/widgets") -> dict[str, Any]:
    build: dict[str, Any] = {
        "id": build_id,
        "branch": "master",
        "commit_sha": f"sha-{build_id}",
        "created_at": created_at,
        "covered_percent": 90.0,
    }
    if repo_name is not None:
        build["repo_name"] = repo_name
    return build


def _builds_page(page: int, pages: int, builds: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"page": page, "pages": pages, "total": pages * 10, "builds": builds})


class TestParseRepositories:
    @pytest.mark.parametrize("raw", [None, "", "   \n  ", " , , ", "not-owner-repo"])
    def test_invalid_raises(self, raw: str | None) -> None:
        with pytest.raises(ValueError):
            parse_repositories(raw)

    def test_rejects_too_many_repositories(self) -> None:
        raw = "\n".join(f"acme/repo{i}" for i in range(MAX_REPOSITORIES + 1))
        with pytest.raises(ValueError, match="Too many repositories"):
            parse_repositories(raw)


class TestFetchJson:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status: int) -> None:
        result = _driver().run("builds", always(ScriptedResponse(status=status)))

        assert isinstance(result.raised, CoverallsRetryableError)
        assert set(result.paths) == {"/github/acme/widgets.json"}

    def test_other_client_error_raises(self) -> None:
        result = _driver().run("builds", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/github/acme/widgets.json"]


class TestIncrementalCutoff:
    @pytest.mark.parametrize(
        "value, lookback, expected",
        [
            # The DB hands the watermark back as a datetime or an ISO string; both must resolve.
            (datetime(2021, 4, 16, 12, 0, tzinfo=UTC), None, datetime(2021, 4, 16, 12, 0, tzinfo=UTC)),
            ("2021-04-16T12:00:00Z", None, datetime(2021, 4, 16, 12, 0, tzinfo=UTC)),
            # The safety lookback re-pulls a window before the watermark; merge dedupes it.
            (
                datetime(2021, 4, 16, 12, 0, tzinfo=UTC),
                COVERALLS_ENDPOINTS["builds"].incremental_lookback,
                datetime(2021, 4, 15, 12, 0, tzinfo=UTC),
            ),
            (None, None, None),
            ("not-a-date", None, None),
        ],
    )
    def test_cutoff(self, value: Any, lookback: Any, expected: datetime | None) -> None:
        assert _incremental_cutoff(value, lookback) == expected


class TestGetBuildsRows:
    def test_stops_on_empty_page(self) -> None:
        # Past-the-end pages return an empty builds list; the walk must terminate rather than loop.
        result = _driver().run("builds", [_builds_page(1, 0, [])])

        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/github/acme/widgets.json"]

    def test_incremental_stops_at_watermark(self) -> None:
        # The feed is newest-first: once a build at or before the cutoff shows up, later pages are
        # all older, so an incremental sync must not fetch them.
        result = _driver().run(
            "builds",
            [_builds_page(1, 5, [_build(20, "2021-04-16T17:46:20Z"), _build(10, "2021-04-13T18:45:20Z")])],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2021, 4, 16, 0, 0, tzinfo=UTC),
        )

        # The page containing the old build is still yielded (merge dedupes), but no further page is fetched.
        assert result.raised is None
        assert len(result.items) == 1
        assert [row["id"] for row in result.rows] == [20, 10]
        assert result.params("page") == ["1"]

    def test_skips_404_repository_and_continues(self) -> None:
        # One typo'd or private repository must not kill the sync for the others.
        result = _driver("acme/nope\nacme/gadgets").run(
            "builds",
            [
                ScriptedResponse(status=404),
                _builds_page(1, 1, [_build(30, "2021-04-16T17:46:20Z", repo_name="acme/gadgets")]),
            ],
        )

        assert result.raised is None
        assert [[row["id"] for row in batch] for batch in result.items] == [[30]]
        assert result.paths == ["/github/acme/nope.json", "/github/acme/gadgets.json"]

    def test_saves_state_after_each_page_and_between_repositories(self) -> None:
        interrupted = _driver().run("builds", [_builds_page(1, 2, [_build(20, "2021-04-16T17:46:20Z")])])
        # The cursor for page 2 reaches storage after the next page reaches the pipeline.
        assert isinstance(interrupted.raised, UnexpectedRequest)
        assert interrupted.saved_states == [CoverallsResumeConfig(repository="acme/widgets", page=2)]
        assert interrupted.committed_states == []
        assert interrupted.final_state is None

        result = _driver("acme/widgets\nacme/gadgets").run(
            "builds",
            [
                _builds_page(1, 2, [_build(20, "2021-04-16T17:46:20Z")]),
                _builds_page(2, 2, [_build(10, "2021-04-13T18:45:20Z")]),
                _builds_page(1, 1, [_build(30, "2021-04-17T00:00:00Z", repo_name="acme/gadgets")]),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "1"]
        assert result.saved_states == [
            CoverallsResumeConfig(repository="acme/widgets", page=2),
            CoverallsResumeConfig(repository="acme/gadgets", page=1),
        ]
        assert result.committed_states == result.saved_states

    def test_resumes_from_saved_repository_and_page(self) -> None:
        # A resumed sync must skip completed repositories and start the bookmarked one at the saved
        # page, not restart the whole walk.
        result = _driver("acme/widgets\nacme/gadgets").run(
            "builds",
            [_builds_page(3, 3, [_build(5, "2021-01-01T00:00:00Z", repo_name="acme/gadgets")])],
            resume_state=CoverallsResumeConfig(repository="acme/gadgets", page=3),
        )

        assert result.raised is None
        assert len(result.items) == 1
        assert result.urls == [_builds_url("github", "acme/gadgets", 3)]


class TestGetRepositoryRows:
    def test_requires_api_token(self) -> None:
        result = _driver().run("repositories", [])

        assert isinstance(result.raised, ValueError)
        assert "personal API token" in str(result.raised)
        assert result.requests == []

    def test_yields_row_per_repository_with_key_columns(self) -> None:
        # `service` and `name` form the primary key, so they must be present even if the API
        # response omits them.
        result = _driver("acme/widgets\nacme/nope\nacme/gadgets", api_token="tok").run(
            "repositories",
            [
                ScriptedResponse(json={"comment_on_pull_requests": True, "repo_token": "secret-upload-token"}),
                ScriptedResponse(status=404),
                ScriptedResponse(json={"name": "acme/gadgets", "send_build_status": False, "token": "secret"}),
            ],
        )

        assert result.raised is None
        assert len(result.items) == 2
        assert result.items[0][0]["service"] == "github"
        assert result.items[0][0]["name"] == "acme/widgets"
        assert result.items[1][0]["name"] == "acme/gadgets"
        # The response's secret coverage-upload token must never be persisted as warehouse data.
        for batch in result.items:
            assert not any("token" in key for key in batch[0])
        assert result.session_options == [{"capture": False}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            (404, False),
            (500, False),
        ],
    )
    def test_builds_feed_status_mapping(self, status: int, expected_valid: bool) -> None:
        script = always(ScriptedResponse(status=status)) if status == 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            is_valid, _ = validate_credentials("github", "acme/widgets", None)

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/github/acme/widgets.json"}

    def test_invalid_repositories_fail_without_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("github", "", None)

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            is_valid, message = validate_credentials("github", "acme/widgets", None)

        assert is_valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/github/acme/widgets.json"}

    def test_repositories_schema_requires_token(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            is_valid, message = validate_credentials("github", "acme/widgets", None, schema_name="repositories")

        assert is_valid is False
        assert message is not None and "token" in message
        assert len(network.requests_log) == 1

    @pytest.mark.parametrize(
        "token_status, expected_valid",
        [
            (200, True),
            (401, False),
            # Coveralls answers 404 (not 401) for unauthorized repos-API requests too.
            (404, False),
        ],
    )
    def test_repositories_schema_probes_token(self, token_status: int, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(), ScriptedResponse(status=token_status)]) as network:
            is_valid, _ = validate_credentials("github", "acme/widgets", "tok", schema_name="repositories")

        assert is_valid is expected_valid
        assert [request.path for request in network.requests_log] == [
            "/github/acme/widgets.json",
            "/api/v1/repos/github/acme/widgets",
        ]
        assert network.requests_log[1].headers["authorization"] == "token tok"
        assert network.session_options == [{}, {"capture": False}]


class TestCoverallsSource:
    def test_only_builds_is_partitioned(self) -> None:
        builds = _driver(api_token="tok").run("builds", [_builds_page(1, 0, [])])
        repositories = _driver(api_token="tok").run("repositories", [ScriptedResponse(json={})])

        assert builds.raised is None
        assert repositories.raised is None
        assert builds.response is not None
        assert repositories.response is not None
        assert builds.response.partition_mode == "datetime"
        assert builds.response.partition_keys == ["created_at"]
        assert repositories.response.partition_mode is None
        assert repositories.response.partition_keys is None

    def test_invalid_repositories_raise(self) -> None:
        result = _driver("").run("builds", [])

        assert isinstance(result.raised, ValueError)
