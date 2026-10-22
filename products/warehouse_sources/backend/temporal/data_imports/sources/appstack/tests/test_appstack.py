from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack import (
    AppstackResumeConfig,
    _export_window_start,
    _to_unix_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source import AppstackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstack import (
    AppstackSourceConfig,
)


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), 1772593094),
            ("date_value", date(2026, 3, 4), 1772582400),
            ("epoch_int", 1772593094, 1772593094),
            ("epoch_float", 1772593094.9, 1772593094),
            ("iso_string", "2026-03-04T02:58:14+00:00", 1772593094),
            ("iso_string_z_suffix", "2026-03-04T02:58:14Z", 1772593094),
            ("epoch_string", "1772593094", 1772593094),
            ("garbage_string", "not-a-timestamp", 0),
            ("negative_epoch_clamped", -5, 0),
        ]
    )
    def test_conversion(self, _label: str, value: Any, expected: int) -> None:
        assert _to_unix_seconds(value) == expected


class TestExportWindowStart:
    @parameterized.expand(
        [
            # Full refresh must always export the full history regardless of any stored watermark.
            ("full_refresh_ignores_watermark", False, datetime(2026, 3, 4, tzinfo=UTC), 0),
            # First incremental sync has no watermark yet and also backfills everything.
            ("incremental_without_watermark", True, None, 0),
            ("incremental_with_watermark", True, datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094),
        ]
    )
    def test_window_start(self, _label: str, incremental: bool, last_value: Any, expected: int) -> None:
        assert _export_window_start(incremental, last_value) == expected


class TestAppstackSource:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(AppstackSource(), AppstackSourceConfig(api_key="key"))

    @staticmethod
    def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
        return ScriptedResponse(json={"data": rows, "total_count": len(rows)})

    def test_paginator_never_trusts_total_count(self) -> None:
        # Appstack's `total_count` counts the current page, not the whole window; a paginator
        # reading it as a grand total would stop after the first page and silently truncate.
        result = self._driver().run(
            "events",
            [self._page([{"event_id": str(index)} for index in range(PAGE_SIZE)]), self._page([{"event_id": "last"}])],
        )

        assert result.raised is None
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1]["event_id"] == "last"

    def test_client_session_disables_sample_capture(self) -> None:
        # Export rows carry device/user identifiers the sample scrubbers can't recognise; the client
        # must run on a capture=False session so response bodies stay out of shared sample storage.
        result = self._driver().run("events", [self._page([{"event_id": "one"}])])

        assert result.raised is None
        assert result.rows[0]["event_id"] == "one"
        assert result.session_options[0]["capture"] is False

    def test_resume_replays_pinned_window_at_saved_offset(self) -> None:
        # Offsets are positions within one export window: a resumed attempt must reuse the saved
        # window's `timestamp`, not re-derive it from a watermark that advanced mid-walk.
        result = self._driver().run(
            "events",
            [self._page([{"event_id": "resumed"}])],
            resume_state=AppstackResumeConfig(offset=30000, window_start=1772593094),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("timestamp") == ["1772593094"]
        assert result.params("offset") == ["30000"]
        assert result.rows[0]["event_id"] == "resumed"

    def test_resume_hook_saves_offset_with_window(self) -> None:
        result = self._driver().run(
            "events",
            [
                self._page([{"event_id": str(index)} for index in range(PAGE_SIZE)]),
                self._page([{"event_id": str(index)} for index in range(PAGE_SIZE, PAGE_SIZE * 2)]),
                self._page([{"event_id": "last"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        # Pages with a next offset save checkpoints. The terminal page saves none.
        assert result.raised is None
        assert result.params("offset") == ["0", str(PAGE_SIZE), str(PAGE_SIZE * 2)]
        assert result.saved_states == [
            AppstackResumeConfig(offset=PAGE_SIZE, window_start=1772593094),
            AppstackResumeConfig(offset=PAGE_SIZE * 2, window_start=1772593094),
        ]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _label: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == "/api/v1/export"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "key"

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_errors_raise(self, _label: str, status_code: int) -> None:
        # Transient/unexpected statuses must not be reported as an invalid API key — they raise.
        with scripted_network(always(ScriptedResponse(status=status_code))):
            with pytest.raises(HTTPError):
                validate_credentials("key")

    def test_probe_disables_sample_capture(self) -> None:
        # The probe hits the same export endpoint, so its response body must not be captured either.
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("the-key") is True

        assert network.session_options[0]["capture"] is False
