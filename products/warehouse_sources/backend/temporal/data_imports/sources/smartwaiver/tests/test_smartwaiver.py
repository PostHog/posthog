from datetime import UTC, date, datetime
from typing import Any

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartwaiver import (
    SmartwaiverSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.smartwaiver import (
    CHECKINS_MAX_OFFSET,
    PAGE_SIZE,
    SmartwaiverResumeConfig,
    _clamp_before_current_hour,
    _format_dts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source import SmartwaiverSource

_NOW = datetime(2026, 7, 8, 15, 42, 30, tzinfo=UTC)
# `fromDts` must not be within the current hour, so recent cursors clamp to 14:59:59.
_HOUR_BOUNDARY = "2026-07-08T14:59:59"


def _response(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _waiver_body(ids: list[str]) -> dict[str, Any]:
    return {"type": "waivers", "waivers": [{"waiverId": i} for i in ids]}


def _checkin_body(ids: list[int], more: bool) -> dict[str, Any]:
    return {
        "type": "checkins",
        "checkins": {"moreCheckins": more, "checkins": [{"checkinId": i, "position": 0} for i in ids]},
    }


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(SmartwaiverSource(), SmartwaiverSourceConfig(api_key="key")).run(endpoint, script, **inputs)


class TestFormatDts:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            # Smartwaiver responses carry naive space-separated timestamps; they must round-trip
            # into the `T`-separated form the API accepts for `fromDts`.
            ("api_response_string", "2018-01-01 12:32:16", "2018-01-01T12:32:16"),
            ("iso_string", "2018-01-01T12:32:16", "2018-01-01T12:32:16"),
            ("unparseable_string_passthrough", "not-a-date", "not-a-date"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_dts(value) == expected


class TestClampBeforeCurrentHour:
    @parameterized.expand(
        [
            ("old_value_untouched", "2026-01-01 10:00:00", "2026-01-01T10:00:00"),
            ("within_current_hour_clamped", "2026-07-08 15:30:00", _HOUR_BOUNDARY),
            ("future_value_clamped", datetime(2026, 7, 9, 1, 0, 0, tzinfo=UTC), _HOUR_BOUNDARY),
        ]
    )
    def test_clamp(self, _name: str, value: Any, expected: str) -> None:
        assert _clamp_before_current_hour(value, _NOW) == expected


class TestWaivers:
    def test_empty_second_page_ends_pagination(self) -> None:
        full_page = [str(i) for i in range(PAGE_SIZE)]

        result = _run("waivers", [_response(_waiver_body(full_page)), _response(_waiver_body([]))])

        assert result.saved_states == [SmartwaiverResumeConfig(next_offset=1, from_dts=None)]

    def test_resumes_from_saved_offset_and_window(self) -> None:
        result = _run(
            "waivers",
            [_response(_waiver_body(["w1"]))],
            resume_state=SmartwaiverResumeConfig(next_offset=3, from_dts="2026-01-01T00:00:00"),
        )

        assert [r["waiverId"] for r in result.rows] == ["w1"]
        assert result.requests[0].param("offset") == "3"
        assert result.requests[0].param("fromDts") == "2026-01-01T00:00:00"

    @parameterized.expand(
        [
            # Old cursor is left untouched (already before the current hour).
            ("old_cursor", "2026-01-01 10:00:00", "2026-01-01T10:00:00"),
            # A cursor within the current hour clamps to the hour boundary.
            ("within_current_hour", "2026-07-08 15:30:00", _HOUR_BOUNDARY),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_incremental_cursor_added_and_clamped(self, _name, cursor, expected) -> None:
        result = _run(
            "waivers",
            [_response(_waiver_body(["w1"]))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=cursor,
        )

        assert result.requests[0].param("fromDts") == expected


class TestCheckins:
    @time_machine.travel(_NOW, tick=False)
    def test_incremental_sync_starts_window_at_watermark(self) -> None:
        result = _run(
            "checkins",
            [_response(_checkin_body([1], more=False))],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-01 08:00:00",
        )

        assert result.requests[0].param("fromDts") == "2026-06-01T08:00:00"
        assert result.requests[0].param("toDts") == _HOUR_BOUNDARY

    @time_machine.travel(_NOW, tick=False)
    def test_paginates_while_more_checkins_and_saves_state(self) -> None:
        result = _run(
            "checkins",
            [_response(_checkin_body([1], more=True)), _response(_checkin_body([2], more=False))],
        )

        assert [r["checkinId"] for r in result.rows] == [1, 2]
        assert result.params("offset") == ["0", "1"]
        assert result.saved_states == [
            SmartwaiverResumeConfig(next_offset=1, from_dts="2000-01-01T00:00:00", to_dts=_HOUR_BOUNDARY)
        ]

    def test_stops_at_offset_cap(self) -> None:
        # A window with more results past the API's offset cap must terminate, not loop, and must
        # not persist a resume state past the cap.
        result = _run(
            "checkins",
            [_response(_checkin_body([1], more=True))],
            resume_state=SmartwaiverResumeConfig(
                next_offset=CHECKINS_MAX_OFFSET, from_dts="2000-01-01T00:00:00", to_dts=_HOUR_BOUNDARY
            ),
        )

        assert [r["checkinId"] for r in result.rows] == [1]
        assert len(result.requests) == 1
        assert result.requests[0].param("offset") == str(CHECKINS_MAX_OFFSET)
        assert result.saved_states == []


class TestSmartwaiverSourceResponse:
    @parameterized.expand(
        [
            ("templates", ["templateId"], None),
            ("waivers", ["waiverId"], ["createdOn"]),
            ("checkins", ["checkinId", "position"], ["date"]),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], expected_partition_keys: list[str] | None
    ) -> None:
        response = _run(endpoint, always(_response(_waiver_body([])))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.partition_keys == expected_partition_keys
        # List order is undocumented, so the watermark must only advance on completed syncs.
        assert response.sort_mode == "desc"
