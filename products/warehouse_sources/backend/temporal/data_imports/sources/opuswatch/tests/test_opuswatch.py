from datetime import date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opuswatch import (
    OPUSWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.opuswatch import (
    OPUSWatchResumeConfig,
    build_date_window_params,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.source import OPUSWatchSource

TODAY = date(2025, 1, 10)


class TestBuildDateWindowParams:
    @pytest.mark.parametrize(
        ("start_date", "should_use_incremental_field", "last_value", "expected"),
        [
            # Full refresh: CREATED window from the configured start date up to today.
            ("20250101", False, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            # Blank start date falls back to the default.
            (None, False, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            ("  ", False, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            # First incremental run has no watermark yet -> CREATED window.
            ("20250101", True, None, {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
            # Incremental with a watermark: UPDATED window covering watermark day -> today.
            ("20250101", True, datetime(2025, 1, 8, 15, 30), {"filter_date_by": "UPDATED", "days_till_date": "3"}),
            ("20250101", True, "2025-01-08T15:30:00Z", {"filter_date_by": "UPDATED", "days_till_date": "3"}),
            # Watermark on today's date still requests at least one day.
            ("20250101", True, datetime(2025, 1, 10, 1, 0), {"filter_date_by": "UPDATED", "days_till_date": "1"}),
            # An unparseable watermark falls back to the CREATED window rather than failing.
            ("20250101", True, "not-a-date", {"filter_date_by": "CREATED", "date": "20250101", "days_from_date": "10"}),
        ],
    )
    def test_window_params(
        self,
        start_date: Optional[str],
        should_use_incremental_field: bool,
        last_value: Any,
        expected: dict[str, str],
    ):
        params = build_date_window_params(start_date, should_use_incremental_field, last_value, today=TODAY)

        for key in ("return_breaks", "return_leaves", "return_archived"):
            assert params.pop(key) == "true"
        assert params == expected


class TestOPUSWatchSourceTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(OPUSWatchSource(), OPUSWatchSourceConfig(api_key="test-key", start_date="20250101"))

    def test_client_endpoint_wraps_single_object_as_one_row(self) -> None:
        row = {"name": "Acme Nursery", "updatedTimestamp": "2025-01-05T00:00:00Z"}
        result = self._driver().run("client", [ScriptedResponse(json=row)])

        assert result.raised is None
        assert result.rows == [row]
        assert result.requests[0].headers["key"] == "test-key"

    @pytest.mark.parametrize("endpoint", ["registrations", "sessions"])
    def test_transactional_pagination_advances_offset_and_checkpoints(self, endpoint: str) -> None:
        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.opuswatch.PAGE_SIZE", 2):
            responses = [
                ScriptedResponse(json={"data": [{"id": "1"}, {"id": "2"}]}),
                ScriptedResponse(json={"data": [{"id": "3"}, {"id": "4"}]}),
                ScriptedResponse(json={"data": [{"id": "5"}]}),
            ]
            result = self._driver().run(endpoint, responses)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3", "4", "5"]
        assert result.params("offset") == ["0", "2", "4"]
        assert result.params("limit") == ["2", "2", "2"]
        # Full refresh requests the CREATED window from the start date on every page.
        assert result.params("filter_date_by") == ["CREATED"] * 3
        assert result.params("date") == ["20250101"] * 3

        assert result.saved_states == [OPUSWatchResumeConfig(offset=2), OPUSWatchResumeConfig(offset=4)]

    def test_incremental_run_requests_updated_window(self) -> None:
        result = self._driver().run(
            "registrations",
            [ScriptedResponse(json={"data": [{"id": "1", "updatedTimestamp": "2025-01-09T10:00:00Z"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 8, 12, 0),
        )

        assert result.raised is None
        assert result.requests[0].param("filter_date_by") == "UPDATED"
        assert result.requests[0].param("days_till_date") is not None
        assert result.requests[0].param("date") is None

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        with patch("products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.opuswatch.PAGE_SIZE", 2):
            result = self._driver().run(
                "registrations",
                [ScriptedResponse(json={"data": [{"id": "5"}]})],
                resume_state=OPUSWatchResumeConfig(offset=4),
            )

        assert result.raised is None
        assert result.params("offset") == ["4"]
        assert result.saved_states == []
