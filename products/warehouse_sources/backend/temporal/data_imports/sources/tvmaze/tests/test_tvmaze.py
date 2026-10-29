from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tvmaze import TVMazeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.source import TVMazeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.tvmaze import (
    UPDATES_CHUNK_SIZE,
    TVMazeResumeConfig,
    check_connection,
)


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
