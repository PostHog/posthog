import base64
from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onfleet import (
    OnfleetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet import onfleet as onfleet_module
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.onfleet import (
    OnfleetResumeConfig,
    _to_epoch_ms,
    get_credentials_status,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.source import OnfleetSource


def _driver() -> SourceDriver:
    return SourceDriver(OnfleetSource(), OnfleetSourceConfig(api_key="key"))


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (1700000000000, 1700000000000),
            (1700000000000.5, 1700000000000),
            ("1700000000000", 1700000000000),
            ("not-a-number", None),
            # datetime/date must convert to MILLISECONDS, not seconds — the crux of Onfleet's `from`.
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp()) * 1000),
        ],
    )
    def test_to_epoch_ms_values(self, value: Any, expected: int | None) -> None:
        assert _to_epoch_ms(value) == expected


class TestBasicAuth:
    def test_api_key_is_username_with_empty_password(self) -> None:
        # Onfleet Basic auth: API key as username, empty password.
        result = _driver().run("workers", [ScriptedResponse(json=[{"id": "w1"}])])

        assert result.raised is None
        token = result.requests[0].headers["authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == "key:"


class TestGetRowsPaginated:
    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "tasks",
            [ScriptedResponse(json={"tasks": [{"id": "9"}]})],
            resume_state=OnfleetResumeConfig(last_id="saved", from_ms=1234),
        )

        assert result.raised is None
        assert result.requests[0].param("lastId") == "saved"
        assert result.requests[0].param("from") == "1234"

    def test_empty_page_with_advancing_cursor_keeps_paginating(self) -> None:
        # A page can be empty yet still carry an advancing lastId; pagination must continue
        # (not terminate) so later, non-empty pages are not skipped.
        result = _driver().run(
            "tasks",
            [
                ScriptedResponse(json={"lastId": "p2", "tasks": []}),
                ScriptedResponse(json={"tasks": [{"id": "1"}]}),  # no lastId -> final page
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1"]
        assert result.requests[1].param("lastId") == "p2"
        # No rows were yielded for the empty page, so no checkpoint was saved for it.
        assert result.saved_states == []

    def test_non_advancing_cursor_terminates(self) -> None:
        # A repeated lastId must not loop forever.
        result = _driver().run(
            "tasks",
            [
                ScriptedResponse(json={"lastId": "x", "tasks": [{"id": "1"}]}),
                ScriptedResponse(json={"lastId": "x", "tasks": [{"id": "1"}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v2/tasks/all", "/api/v2/tasks/all"]
        assert [row["id"] for row in result.rows] == ["1", "1"]


class TestRoutePlans:
    @pytest.mark.parametrize("to_inclusive", [True, False])
    def test_window_walk_yields_every_route_plan_once(
        self, monkeypatch: pytest.MonkeyPatch, to_inclusive: bool
    ) -> None:
        monkeypatch.setattr(onfleet_module, "ROUTE_PLANS_LIMIT", 3)
        monkeypatch.setattr(onfleet_module, "_now_ms", lambda: 128)
        # Rows sit on the power-of-two window boundaries the walk produces.
        created_times = {
            f"r{index}": created for index, created in enumerate([0, 0, 4, 6, 8, 10, 10, 12, 16, 30, 32, 47, 64, 100])
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            start, end, limit = (
                int(request.param(name) or 0) for name in ("createdTimeFrom", "createdTimeTo", "limit")
            )
            matches = [
                {"id": plan_id, "timeCreated": created}
                for plan_id, created in reversed(created_times.items())
                if start <= created and (created <= end if to_inclusive else created < end)
            ]
            return ScriptedResponse(json=matches[:limit])

        result = _driver().run("route_plans", respond)

        assert result.raised is None
        assert sorted(row["id"] for row in result.rows) == sorted(created_times)

    def test_saturated_minimum_window_fails_the_sync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(onfleet_module, "ROUTE_PLANS_LIMIT", 2)
        monkeypatch.setattr(onfleet_module, "_now_ms", lambda: 8)
        full_page = [{"id": "a", "timeCreated": 0}, {"id": "b", "timeCreated": 0}]

        result = _driver().run("route_plans", always(ScriptedResponse(json=full_page)))

        assert isinstance(result.raised, ValueError)
        assert result.rows == []

    @pytest.mark.parametrize(
        "inputs, resume_state, expected_from, expected_to",
        [
            ({}, None, "0", "2000"),
            ({"incremental_field": "timeCreated", "db_incremental_field_last_value": 1200}, None, "1200", "2000"),
            ({}, OnfleetResumeConfig(from_ms=1000, window_ms=500), "1000", "1500"),
        ],
    )
    def test_first_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
        inputs: dict[str, Any],
        resume_state: OnfleetResumeConfig | None,
        expected_from: str,
        expected_to: str,
    ) -> None:
        monkeypatch.setattr(onfleet_module, "_now_ms", lambda: 2000)

        result = _driver().run("route_plans", always(ScriptedResponse(json=[])), resume_state=resume_state, **inputs)

        assert result.raised is None
        assert result.paths[0] == "/api/v2/routePlans"
        assert result.requests[0].param("createdTimeFrom") == expected_from
        assert result.requests[0].param("createdTimeTo") == expected_to


class TestGetCredentialsStatus:
    def test_returns_none_on_transport_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert get_credentials_status("key") is None

        assert {request.path for request in network.requests_log} == {"/api/v2/organization"}
