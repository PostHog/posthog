from typing import Any

import pytest

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.sources.tvmaze._config import TVMazeSourceConfig
from products.warehouse_sources.sources.tvmaze.source import TVMazeSource
from products.warehouse_sources.sources.tvmaze.tvmaze import UPDATES_CHUNK_SIZE, TVMazeResumeConfig, check_connection


def _run(endpoint: str, script: Script, resume_state: TVMazeResumeConfig | None = None) -> DriveResult:
    return SourceDriver(TVMazeSource(), TVMazeSourceConfig()).run(endpoint, script, resume_state=resume_state)


def _json(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestIndexPagination:
    """End-to-end pagination + resume behaviour of the show/person indexes."""

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = _run(
            "shows",
            [_json([{"id": 1750}]), _json([], status=404)],
            resume_state=TVMazeResumeConfig(page=7),
        )

        assert result.params("page") == ["7", "8"]

    def test_starts_from_the_first_page_when_there_is_no_saved_state(self) -> None:
        result = _run("shows", [_json([], status=404)])

        assert result.params("page") == ["0"]


def _shows_index(*show_ids: int) -> list[ScriptedResponse]:
    return [_json([{"id": show_id, "name": f"Show {show_id}"} for show_id in show_ids]), _json([], status=404)]


class TestShowFanout:
    @pytest.mark.parametrize(
        ("endpoint", "child_suffix", "child_row", "expected_specials"),
        [
            ("seasons", "seasons", {"id": 10, "number": 1}, None),
            ("episodes", "episodes", {"id": 20, "season": 1, "number": None, "type": "insignificant_special"}, "1"),
            ("cast", "cast", {"person": {"id": 30}, "character": {"id": 40}, "self": False, "voice": False}, None),
        ],
    )
    def test_walks_every_show_once_and_tags_rows_with_the_show(
        self, endpoint: str, child_suffix: str, child_row: dict[str, Any], expected_specials: str | None
    ) -> None:
        result = _run(
            endpoint,
            route(
                {
                    "/shows": _shows_index(1, 2, 3),
                    f"/shows/1/{child_suffix}": [_json([child_row])],
                    # A show deleted after the index page was read.
                    f"/shows/2/{child_suffix}": [_json({"name": "Not Found", "status": 404}, status=404)],
                    f"/shows/3/{child_suffix}": [_json([child_row, child_row])],
                }
            ),
        )

        assert result.raised is None
        assert [row["show_id"] for row in result.rows] == [1, 3, 3]
        assert all("_shows_id" not in row for row in result.rows)
        # Child lists are unpaginated: one request per show, never a ?page= walk.
        assert result.paths == [
            "/shows",
            f"/shows/1/{child_suffix}",
            f"/shows/2/{child_suffix}",
            f"/shows/3/{child_suffix}",
            "/shows",
        ]
        assert result.params("page") == ["0", None, None, None, "1"]
        assert result.params("specials") == [None] + [expected_specials] * 3 + [None]
        assert result.response is not None
        assert result.response.sort_mode is None

    def test_cast_rows_expose_person_and_character_ids(self) -> None:
        result = _run(
            "cast",
            route(
                {
                    "/shows": _shows_index(1),
                    "/shows/1/cast": [
                        _json(
                            [
                                {"person": {"id": 7}, "character": {"id": 70}},
                                {"person": {"id": 8}, "character": None},
                            ]
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [(r["show_id"], r["person_id"], r["character_id"]) for r in result.rows] == [(1, 7, 70), (1, 8, None)]

    def test_resume_skips_finished_shows_and_starts_at_the_saved_index_page(self) -> None:
        result = _run(
            "episodes",
            route(
                {
                    "/shows": [_json([{"id": 251}, {"id": 252}]), _json([], status=404)],
                    "/shows/252/episodes": [_json([{"id": 900}])],
                }
            ),
            resume_state=TVMazeResumeConfig(
                fanout_state={"parent": {"page": 1}, "completed": ["/shows/251/episodes?specials=1"]}
            ),
        )

        assert result.raised is None
        assert [(r["show_id"], r["id"]) for r in result.rows] == [(252, 900)]
        assert result.paths == ["/shows", "/shows/252/episodes", "/shows"]
        assert result.params("page")[0] == "1"
        assert all(state.page is None and state.fanout_state for state in result.saved_states)


class TestUpdatesEndpoints:
    def test_large_map_is_yielded_in_chunks(self) -> None:
        payload = {str(i): i for i in range(UPDATES_CHUNK_SIZE + 1)}

        result = _run("show_updates", [_json(payload)])

        assert [len(page) for page in result.items] == [UPDATES_CHUNK_SIZE, 1]


class TestCheckConnection:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (403, False),
            (503, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(_json([], status=status_code))):
            valid, error = check_connection()

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_network_error_returns_message(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            valid, error = check_connection()

        assert valid is False
        assert error is not None and "boom" in error
