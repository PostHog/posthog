from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.everhour import (
    EARLIEST_FROM_DATE,
    EVERHOUR_BASE_URL,
    EverhourResumeConfig,
    _date_window,
    _format_date,
    _with_query,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.settings import (
    ENDPOINTS,
    EVERHOUR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.source import EverhourSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.everhour import (
    EverhourSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(EverhourSource(), EverhourSourceConfig(api_key="key"))


def _items(start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": i} for i in range(start, start + count)]


class TestWithQuery:
    def test_drops_none_values(self) -> None:
        assert _with_query("/clients", {"limit": None}) == f"{EVERHOUR_BASE_URL}/clients"


class TestFormatDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (date(2026, 3, 4), "2026-03-04"),
            (datetime(2026, 3, 4, 23, 30, tzinfo=UTC), "2026-03-04"),
            (datetime(2026, 3, 4, 12, 0), "2026-03-04"),
            ("2026-03-04", "2026-03-04"),
        ],
    )
    def test_format_date(self, value: Any, expected: str) -> None:
        assert _format_date(value) == expected


class TestDateWindow:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_incremental_floors_from_to_watermark_day(self) -> None:
        window = _date_window(
            EVERHOUR_ENDPOINTS["time_records"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 5, 1),
        )
        assert window == {"from": "2026-05-01", "to": "2026-06-15"}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key") is expected

        assert {request.path for request in network.requests_log} == {"/users/me"}

    def test_swallows_exceptions(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("key") is False

        assert {request.path for request in network.requests_log} == {"/users/me"}


class TestBuildInitialUrls:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_time_records_bakes_in_date_window(self) -> None:
        result = _driver().run(
            "time_records",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
        )
        assert result.raised is None
        assert result.paths == ["/time-records"]
        assert result.requests[0].param("limit") == "50"
        assert result.requests[0].param("from") == EARLIEST_FROM_DATE
        assert result.requests[0].param("to") == "2026-06-15"

    def test_project_fan_out_one_url_per_project(self) -> None:
        result = _driver().run(
            "tasks",
            [
                ScriptedResponse(json=[{"id": "p1"}, {"id": "p2"}]),
                ScriptedResponse(json=[]),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/projects", "/projects/p1/tasks", "/projects/p2/tasks"]
        assert result.params("limit") == ["100", "100", "100"]


class TestGetRows:
    @pytest.mark.parametrize(
        "endpoint, child_path, expected_rows",
        [
            ("tasks", "tasks", [{"id": "a", "project_id": "ev:1"}, {"id": "b", "project_id": "as:2"}]),
            ("custom_fields", "fields", [{"id": "a", "project_id": "ev:1"}, {"id": "b", "project_id": "as:2"}]),
            ("sections", "sections", [{"id": "a"}, {"id": "b"}]),
        ],
    )
    def test_project_fan_out_drains_parents(
        self, endpoint: str, child_path: str, expected_rows: list[dict[str, Any]]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"id": "ev:1"}, {"id": "as:2"}]),
                ScriptedResponse(json=[{"id": "a"}]),
                ScriptedResponse(json=[{"id": "b"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == expected_rows
        # After draining the first parent, state advances to the second parent URL.
        saved = result.saved_states[0]
        assert saved.current_url == f"{EVERHOUR_BASE_URL}/projects/as:2/{child_path}?limit=100"
        assert saved.remaining_urls == []
        assert result.paths == ["/projects", f"/projects/ev:1/{child_path}", f"/projects/as:2/{child_path}"]

    def test_resumes_from_saved_state(self) -> None:
        resume_url = f"{EVERHOUR_BASE_URL}/clients?limit=100"
        result = _driver().run(
            "clients",
            [ScriptedResponse(json=_items(0, 1))],
            resume_state=EverhourResumeConfig(remaining_urls=[], current_url=resume_url, current_offset=200),
        )

        # The first fetch must continue from the saved offset, not start over.
        assert result.raised is None
        assert result.paths == ["/clients"]
        assert result.params("offset") == ["200"]

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_rows_without_an_id_paginate_on_their_own_key(self) -> None:
        # Timecards carry no `id`, so the pagination guard has to key on (user, date) instead.
        first_page = [{"user": u, "date": "2026-06-01", "workTime": 3600} for u in range(100)]
        result = _driver().run(
            "timecards",
            [
                ScriptedResponse(json=first_page),
                ScriptedResponse(json=[{"user": 0, "date": "2026-06-02", "workTime": 3600}]),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 101
        assert result.params("offset") == ["0", "100"]


class TestEverhourSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = EVERHOUR_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, always(ScriptedResponse(json=[])))
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_fan_out_child_key_includes_parent(self) -> None:
        # A task can belong to multiple projects, so the project id must be part of the key to stay
        # unique table-wide.
        assert EVERHOUR_ENDPOINTS["tasks"].primary_keys == ["project_id", "id"]
