from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tmdb import TMDbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.source import TMDbSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.tmdb import (
    TMDbResumeConfig,
    validate_credentials,
)


def _page_response(rows: list[dict[str, Any]], *, page: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={"page": page, "results": rows, "total_pages": total_pages})


def _source(endpoint: str, script: Script, resume: TMDbResumeConfig | None = None, api_key: str = "k") -> DriveResult:
    driver = SourceDriver(TMDbSource(), TMDbSourceConfig(api_key=api_key))
    return driver.run(endpoint, script, resume_state=resume)


def _not_found() -> ScriptedResponse:
    return ScriptedResponse(status=404, json={"status_code": 34, "success": False})


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint, expected_sort_by",
        [
            ("movie_popular", None),
            ("discover_movies", "vote_count.desc"),
            ("discover_tv", "vote_count.desc"),
        ],
    )
    def test_paginates_until_total_pages_and_saves_state(self, endpoint: str, expected_sort_by: str | None) -> None:
        result = _source(
            endpoint,
            [
                _page_response([{"id": 1}], page=1, total_pages=2),
                _page_response([{"id": 2}], page=2, total_pages=2),
            ],
        )

        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.params("page") == ["1", "2"]
        assert result.requests[0].param("language") == "en-US"
        assert result.params("sort_by") == [expected_sort_by, expected_sort_by]
        # State saved after the first page only (the last page has nothing more to resume to).
        assert result.saved_states == [TMDbResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _source(
            "movie_popular",
            [_page_response([{"id": 5}], page=5, total_pages=5)],
            resume=TMDbResumeConfig(next_page=5),
        )

        assert result.rows == [{"id": 5}]
        # Picks up at page 5, not page 1, and never checkpoints again.
        assert result.params("page") == ["5"]
        assert result.saved_states == []


class TestNonPaginatedEndpoints:
    def test_bare_list_endpoint_yields_rows(self) -> None:
        result = _source("languages", [ScriptedResponse(json=[{"iso_639_1": "en", "name": "English"}])])

        assert result.rows == [{"iso_639_1": "en", "name": "English"}]
        assert result.saved_states == []


class TestPerTitleEndpoints:
    @pytest.mark.parametrize(
        "endpoint, parent_path, child_body, expected_rows",
        [
            (
                "movie_credits",
                "/discover/movie",
                {
                    "id": 1,
                    "cast": [{"id": 10, "credit_id": "c1", "character": "Pilot", "order": 0}],
                    "crew": [{"id": 11, "credit_id": "c2", "department": "Directing", "job": "Director"}],
                },
                [
                    {
                        "id": 10,
                        "credit_id": "c1",
                        "character": "Pilot",
                        "order": 0,
                        "movie_id": 1,
                        "credit_type": "cast",
                    },
                    {
                        "id": 11,
                        "credit_id": "c2",
                        "department": "Directing",
                        "job": "Director",
                        "movie_id": 1,
                        "credit_type": "crew",
                    },
                ],
            ),
            ("movie_credits", "/discover/movie", {"id": 1, "cast": [], "crew": None}, []),
            (
                "tv_aggregate_credits",
                "/discover/tv",
                {
                    "id": 1,
                    "cast": [
                        {
                            "id": 10,
                            "name": "Actor A",
                            "total_episode_count": 5,
                            "roles": [
                                {"credit_id": "r1", "character": "Captain", "episode_count": 3},
                                {"credit_id": "r2", "character": "Twin", "episode_count": 2},
                            ],
                        },
                        {"id": 12, "name": "Actor B", "roles": []},
                    ],
                    "crew": [
                        {
                            "id": 11,
                            "department": "Writing",
                            "jobs": [{"credit_id": "j1", "job": "Writer", "episode_count": 4}],
                        }
                    ],
                },
                [
                    {
                        "id": 10,
                        "name": "Actor A",
                        "total_episode_count": 5,
                        "credit_id": "r1",
                        "character": "Captain",
                        "episode_count": 3,
                        "series_id": 1,
                        "credit_type": "cast",
                    },
                    {
                        "id": 10,
                        "name": "Actor A",
                        "total_episode_count": 5,
                        "credit_id": "r2",
                        "character": "Twin",
                        "episode_count": 2,
                        "series_id": 1,
                        "credit_type": "cast",
                    },
                    {
                        "id": 11,
                        "department": "Writing",
                        "credit_id": "j1",
                        "job": "Writer",
                        "episode_count": 4,
                        "series_id": 1,
                        "credit_type": "crew",
                    },
                ],
            ),
            (
                "tv_seasons",
                "/discover/tv",
                {
                    "id": 1,
                    "name": "Series",
                    "seasons": [{"id": 100, "season_number": 0}, {"id": 101, "season_number": 1}],
                },
                [{"id": 100, "season_number": 0, "series_id": 1}, {"id": 101, "season_number": 1, "series_id": 1}],
            ),
            ("tv_seasons", "/discover/tv", {"id": 1, "name": "Series"}, []),
        ],
    )
    def test_fans_out_over_discover_and_flattens_rows(
        self,
        endpoint: str,
        parent_path: str,
        child_body: dict[str, Any],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        # Title 2 left the catalog after the listing; its 404 must not fail the sync.
        result = _source(
            endpoint,
            route(
                {
                    parent_path: [_page_response([{"id": 1}, {"id": 2}], page=1, total_pages=1)],
                    "/1/credits": [ScriptedResponse(json=child_body)],
                    "/1/aggregate_credits": [ScriptedResponse(json=child_body)],
                    "/tv/1": [ScriptedResponse(json=child_body)],
                    "/2/credits": [_not_found()],
                    "/2/aggregate_credits": [_not_found()],
                    "/tv/2": [_not_found()],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.paths[0] == f"/3{parent_path}"
        assert result.params("sort_by")[0] == "vote_count.desc"
        assert len(result.paths) == 3
        assert result.saved_states[-1].completed is not None
        assert len(result.saved_states[-1].completed) == 2

    def test_resumes_fan_out_after_completed_titles(self) -> None:
        result = _source(
            "movie_credits",
            route(
                {
                    "/discover/movie": [_page_response([{"id": 1}, {"id": 2}], page=1, total_pages=1)],
                    "/movie/2/credits": [ScriptedResponse(json={"id": 2, "cast": [{"credit_id": "c9"}]})],
                }
            ),
            resume=TMDbResumeConfig(completed=["/movie/1/credits"]),
        )

        assert result.raised is None
        assert result.paths == ["/3/discover/movie", "/3/movie/2/credits"]
        assert result.rows == [{"credit_id": "c9", "movie_id": 2, "credit_type": "cast"}]

    def test_episodes_fan_out_over_every_season_of_every_series(self) -> None:
        result = _source(
            "tv_episodes",
            route(
                {
                    "/discover/tv": [_page_response([{"id": 1}, {"id": 2}], page=1, total_pages=1)],
                    "/tv/1": [
                        ScriptedResponse(json={"id": 1, "seasons": [{"season_number": 0}, {"season_number": 1}]})
                    ],
                    "/tv/2": [_not_found()],
                    "/tv/1/season/0": [ScriptedResponse(json={"id": 50, "episodes": []})],
                    "/tv/1/season/1": [
                        ScriptedResponse(
                            json={
                                "id": 51,
                                "episodes": [
                                    {"id": 500, "show_id": 1, "season_number": 1, "episode_number": 1},
                                    {"id": 501, "show_id": 1, "season_number": 1, "episode_number": 2},
                                ],
                            }
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [500, 501]
        assert sorted(result.paths) == sorted(
            ["/3/discover/tv", "/3/tv/1", "/3/tv/2", "/3/tv/1/season/0", "/3/tv/1/season/1"]
        )
        assert result.response is not None
        assert result.response.supports_resume is False
        assert result.saved_states == []


class TestErrorRedaction:
    def test_401_scrubs_api_key_but_preserves_host(self) -> None:
        # The api_key rides in the query string; a 4xx must not leak it into the propagated error,
        # while the base host stays intact so get_non_retryable_errors() can still match on it.
        result = _source(
            "movie_popular", [ScriptedResponse(status=401, json={"status_code": 7})], api_key="supersecret"
        )

        assert isinstance(result.raised, requests.HTTPError)
        message = str(result.raised)
        assert "supersecret" not in message
        assert "https://api.themoviedb.org/3/movie/popular" in message


class TestValidateCredentials:
    @pytest.mark.parametrize("status", [404, 429, 503])
    def test_non_401_failure_does_not_claim_invalid_key(self, status: int) -> None:
        # A transient/service-side failure must not be reported as an invalid credential.
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"

    def test_network_error_does_not_claim_invalid_key(self) -> None:
        with scripted_network(always(ConnectionResetError("reset"))):
            is_valid, message = validate_credentials("k")
        assert is_valid is False
        assert message is not None
        assert message != "Invalid TMDB API key"
