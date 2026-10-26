from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plivo import PlivoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.plivo import (
    PlivoResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.source import PlivoSource

FROZEN_NOW = "2026-07-21 12:00:00"
MESSAGE_URL = "https://api.plivo.com/v1/Account/MA123/Message/"


def _driver() -> SourceDriver:
    return SourceDriver(PlivoSource(), PlivoSourceConfig(auth_id="MA123", auth_token="token"))


def _page(objects: list[dict[str, Any]], total_count: int) -> ScriptedResponse:
    return ScriptedResponse(json={"meta": {"limit": PAGE_SIZE, "total_count": total_count}, "objects": objects})


class TestWindowedEndpoints:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(FROZEN_NOW, tick=False):
            yield

    def test_full_refresh_walks_retention_in_30_day_windows(self) -> None:
        result = _driver().run("messages", [_page([], 0) for _ in range(3)])

        assert result.raised is None
        # 90 days of retention → three contiguous 30-day windows, each filtered server-side.
        assert list(zip(result.params("message_time__gt"), result.params("message_time__lte"), strict=True)) == [
            ("2026-04-22 12:00:00", "2026-05-22 12:00:00"),
            ("2026-05-22 12:00:00", "2026-06-21 12:00:00"),
            ("2026-06-21 12:00:00", "2026-07-21 12:00:00"),
        ]

    def test_incremental_starts_at_cursor_and_filters_server_side(self) -> None:
        result = _driver().run(
            "messages",
            [_page([{"message_uuid": "m1", "message_time": "2026-07-15 09:30:00+00:00"}], 1)],
            incremental_field="message_time",
            db_incremental_field_last_value=datetime(2026, 7, 11, 12, tzinfo=UTC),
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.urls[0].split("?")[0] == MESSAGE_URL
        assert result.params("message_time__gt") == ["2026-07-11 12:00:00"]
        assert result.params("message_time__lte") == ["2026-07-21 12:00:00"]
        assert result.params("limit") == [str(PAGE_SIZE)]
        assert result.params("offset") == ["0"]
        assert [row["message_uuid"] for row in result.rows] == ["m1"]
        # Timestamp strings are parsed so the incremental watermark compares datetimes.
        assert result.rows[0]["message_time"] == datetime(2026, 7, 15, 9, 30, tzinfo=UTC)

    def test_pagination_saves_offset_then_window_checkpoint(self) -> None:
        result = _driver().run(
            "messages",
            [
                _page([{"message_uuid": f"m{i}"} for i in range(PAGE_SIZE)], PAGE_SIZE + 5),
                _page([{"message_uuid": f"m{PAGE_SIZE + i}"} for i in range(5)], PAGE_SIZE + 5),
            ],
            incremental_field="message_time",
            db_incremental_field_last_value=datetime(2026, 7, 11, 12, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert len(result.rows) == PAGE_SIZE + 5
        saved = result.saved_states
        # Mid-window: checkpoint the next page offset with the window bounds pinned.
        assert saved[0].offset == PAGE_SIZE
        assert saved[0].window_start == datetime(2026, 7, 11, 12, tzinfo=UTC).isoformat()
        assert saved[0].window_end == datetime(2026, 7, 21, 12, tzinfo=UTC).isoformat()
        # Window exhausted: checkpoint points at the next window's start with a fresh offset.
        assert saved[-1].window_start == datetime(2026, 7, 21, 12, tzinfo=UTC).isoformat()
        assert saved[-1].offset == 0

    def test_resume_pins_saved_window_and_offset(self) -> None:
        window_start = datetime(2026, 6, 11, 12, tzinfo=UTC)
        window_end = datetime(2026, 7, 11, 12, tzinfo=UTC)
        result = _driver().run(
            "messages",
            [_page([{"message_uuid": "x"}], 1), _page([{"message_uuid": "y"}], 1)],
            resume_state=PlivoResumeConfig(
                window_start=window_start.isoformat(), window_end=window_end.isoformat(), offset=40
            ),
        )

        assert result.raised is None
        # First request resumes the saved window at the saved page offset...
        assert result.params("message_time__gt")[0] == "2026-06-11 12:00:00"
        assert result.params("message_time__lte")[0] == "2026-07-11 12:00:00"
        assert result.params("offset")[0] == "40"
        # ...then the walk continues from the saved window's end to now, from offset 0.
        assert result.params("message_time__gt")[1] == "2026-07-11 12:00:00"
        assert result.params("message_time__lte")[1] == "2026-07-21 12:00:00"
        assert result.params("offset")[1] == "0"


class TestNonWindowedEndpoints:
    def test_recordings_incremental_filters_without_windowing(self) -> None:
        result = _driver().run(
            "recordings",
            [_page([{"recording_id": "r1", "add_time": ""}], 1)],
            incremental_field="add_time",
            # A cursor older than the 90-day MDR/CDR retention must NOT be clamped here —
            # recordings persist until deleted.
            db_incremental_field_last_value=datetime(2025, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.requests[0].path == "/v1/Account/MA123/Recording/"
        assert result.params("add_time__gt") == ["2025-01-01 00:00:00"]
        assert result.params("add_time__lte") == [None]
        # An empty timestamp string stays untouched instead of failing the row.
        assert result.items[0][0]["add_time"] == ""


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("MA123", "token") is expected

        assert {request.path for request in network.requests_log} == {"/v1/Account/MA123/"}


class TestPlivoSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_keys",
        [
            ("messages", ["message_uuid"], ["message_time"]),
            ("calls", ["call_uuid"], ["end_time"]),
            ("recordings", ["recording_id"], ["add_time"]),
            ("applications", ["app_id"], None),
        ],
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        with time_machine.travel(FROZEN_NOW, tick=False):
            result = _driver().run(endpoint, [_page([], 0) for _ in range(3)])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        # Plivo lists return newest-first with no sort param, so the watermark must only be
        # persisted after a fully successful run.
        assert response.sort_mode == "desc"
