from collections.abc import Callable

import pytest

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.sources.waydev._config import WaydevSourceConfig
from products.warehouse_sources.sources.waydev.source import WaydevSource
from products.warehouse_sources.sources.waydev.waydev import WaydevResumeConfig, validate_credentials


class TestWaydevSourceResumeBehavior:
    """End-to-end resume behaviour of ``WaydevSource``, driven through ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(WaydevSource(), WaydevSourceConfig(api_key="test-key"))

    def test_incidents_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "Incidents",
            [ScriptedResponse(json={"current_page": 5, "data": []})],
            resume_state=WaydevResumeConfig(next_page=5),
        )

        assert result.params("page") == ["5"]

    def test_a_single_real_page_still_probes_once_more_before_stopping(self) -> None:
        # stop_after_empty_page means the last real page is always followed by one more
        # request that comes back empty (no total-pages field is documented for this endpoint).
        result = self._driver().run(
            "Incidents",
            [
                ScriptedResponse(json={"current_page": 1, "data": [{"id": 1}]}),
                ScriptedResponse(json={"current_page": 2, "data": []}),
            ],
        )

        assert result.params("page") == ["1", "2"]
        assert result.saved_states == [WaydevResumeConfig(next_page=2)]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = self._driver().run("Incidents", [ScriptedResponse(json={"current_page": 1, "data": []})])

        assert result.params("page") == ["1"]


class TestWaydevListEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "script", "expected_pages", "expected_ids", "expected_query"),
        [
            (
                "Repositories",
                [
                    ScriptedResponse(json={"count": 3, "values": [{"id": 11}, {"id": 12}]}),
                    ScriptedResponse(json={"count": 3, "values": [{"id": 13}]}),
                    ScriptedResponse(json={"count": 3, "values": []}),
                ],
                ["1", "2", "3"],
                [11, 12, 13],
                {"state": "all", "limit": "500"},
            ),
            (
                "Teams",
                [
                    ScriptedResponse(json={"current_page": 1, "last_page": 2, "data": [{"id": 21}, {"id": 22}]}),
                    ScriptedResponse(json={"current_page": 2, "last_page": 2, "data": [{"id": 23}]}),
                ],
                ["1", "2"],
                [21, 22, 23],
                {"limit": "100"},
            ),
            (
                "Teams",
                [ScriptedResponse(json={"current_page": 1, "last_page": 1, "data": []})],
                ["1"],
                [],
                {"limit": "100"},
            ),
            (
                "Contributors",
                [
                    ScriptedResponse(
                        json={
                            "count": 2,
                            "contributors": [
                                {"id": 31, "official_name": "dev.one", "teams": [], "merged_developers": []},
                                {"id": 32, "official_name": "dev.two", "teams": ["Core"], "merged_developers": []},
                            ],
                        }
                    )
                ],
                [None],
                [31, 32],
                {},
            ),
        ],
    )
    def test_walks_pages_and_extracts_rows(
        self,
        endpoint: str,
        script: list[ScriptedResponse],
        expected_pages: list[str | None],
        expected_ids: list[int],
        expected_query: dict[str, str],
    ) -> None:
        result = SourceDriver(WaydevSource(), WaydevSourceConfig(api_key="test-key")).run(endpoint, script)

        assert result.raised is None
        assert result.paths == [f"/v2/{endpoint.lower()}"] * len(expected_pages)
        assert result.params("page") == expected_pages
        for name, value in expected_query.items():
            assert set(result.params(name)) == {value}
        assert [row["id"] for row in result.rows] == expected_ids


def _by_path_and_page(
    answers: dict[tuple[str, str], ScriptedResponse],
) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        return answers[(request.path, request.param("page") or "")]

    return respond


def _values(*ids: int) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(ids), "values": [{"id": i} for i in ids]})


def _members_page(page: int, last_page: int, *ids: int) -> ScriptedResponse:
    return ScriptedResponse(json={"current_page": page, "last_page": last_page, "data": [{"id": i} for i in ids]})


_REPOSITORY_ANSWERS = {
    ("/v2/repositories", "1"): _values(1, 2),
    ("/v2/repositories", "2"): _values(),
}


class TestWaydevFanoutEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "answers", "parent_query", "child_query", "parent_key", "expected_rows"),
        [
            (
                "PullRequests",
                {
                    **_REPOSITORY_ANSWERS,
                    ("/v2/repositories/1/pulls", "1"): _values(10, 11),
                    ("/v2/repositories/1/pulls", "2"): _values(12),
                    ("/v2/repositories/1/pulls", "3"): _values(),
                    # Removed after the listing; the other repository's rows still land.
                    ("/v2/repositories/2/pulls", "1"): ScriptedResponse(
                        status=404, json={"error": {"message": "Not Found!"}}
                    ),
                },
                {"state": "selected", "limit": "500"},
                {},
                "repository_id",
                [(1, 10), (1, 11), (1, 12)],
            ),
            (
                "Commits",
                {
                    **_REPOSITORY_ANSWERS,
                    ("/v2/repositories/1/commits", "1"): _values(20),
                    ("/v2/repositories/1/commits", "2"): _values(),
                    # Commit ids repeat across repositories here, so only the composite key is unique.
                    ("/v2/repositories/2/commits", "1"): _values(20),
                    ("/v2/repositories/2/commits", "2"): _values(),
                },
                {"state": "selected", "limit": "500"},
                {},
                "repository_id",
                [(1, 20), (2, 20)],
            ),
            (
                "TeamMembers",
                {
                    ("/v2/teams", "1"): _members_page(1, 1, 5, 6),
                    ("/v2/teams/5/members", "1"): _members_page(1, 2, 100),
                    ("/v2/teams/5/members", "2"): _members_page(2, 2, 101),
                    ("/v2/teams/6/members", "1"): _members_page(1, 1, 100),
                },
                {"limit": "100"},
                {"limit": "100"},
                "team_id",
                [(5, 100), (5, 101), (6, 100)],
            ),
        ],
    )
    def test_fans_out_over_every_parent_page(
        self,
        endpoint: str,
        answers: dict[tuple[str, str], ScriptedResponse],
        parent_query: dict[str, str],
        child_query: dict[str, str],
        parent_key: str,
        expected_rows: list[tuple[int, int]],
    ) -> None:
        result = SourceDriver(WaydevSource(), WaydevSourceConfig(api_key="test-key")).run(
            endpoint, _by_path_and_page(answers)
        )

        assert result.raised is None
        assert sorted(set(result.paths)) == sorted({path for path, _ in answers})
        parent_requests = [r for r in result.requests if r.path.count("/") == 2]
        child_requests = [r for r in result.requests if r.path.count("/") > 2]
        for request in parent_requests:
            assert {name: request.param(name) for name in parent_query} == parent_query
        for request in child_requests:
            assert {name: values for name, values in request.query.items() if name != "page"} == {
                name: (value,) for name, value in child_query.items()
            }
        assert [(row[parent_key], row["id"]) for row in result.rows] == expected_rows
        assert result.response is not None
        assert result.response.primary_keys == [parent_key, "id"]

    def test_resume_skips_parents_already_finished(self) -> None:
        answers = {
            **_REPOSITORY_ANSWERS,
            ("/v2/repositories/1/commits", "1"): _values(20),
            ("/v2/repositories/1/commits", "2"): _values(),
            ("/v2/repositories/2/commits", "1"): _values(30),
            ("/v2/repositories/2/commits", "2"): _values(),
        }
        driver = SourceDriver(WaydevSource(), WaydevSourceConfig(api_key="test-key"))
        first = driver.run("Commits", _by_path_and_page(answers))
        after_first_repository = next(
            state
            for state in first.saved_states
            if state.fanout_state and state.fanout_state["completed"] == ["/repositories/1/commits"]
        )

        resumed = driver.run("Commits", _by_path_and_page(answers), resume_state=after_first_repository)

        assert resumed.raised is None
        assert "/v2/repositories/1/commits" not in resumed.paths
        assert [(row["repository_id"], row["id"]) for row in resumed.rows] == [(2, 30)]


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(json=[])]) as network:
            assert validate_credentials("token") == (True, 200)
        assert network.requests_log[0].path == "/v2/metrics"
        assert network.requests_log[0].headers["authorization"] == "token"
