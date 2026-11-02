from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recallai import (
    RecallAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.recall_ai import (
    RecallAIResumeConfig,
    _to_iso8601,
    base_url_for_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.settings import USAGE_BACKFILL_DAYS
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.source import RecallAISource

BASE_URL = "https://us-east-1.recall.ai"


def _page(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _drive(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    config = RecallAISourceConfig(api_key="test-key", region="us-east-1")
    return SourceDriver(RecallAISource(), config).run(endpoint, script, **inputs)


class TestRecallAIRequestShaping:
    INCREMENTAL_PARAMS = {
        "recordings": "created_at_after",
        "transcripts": "created_at_after",
        "participant_events": "created_at_after",
        "meeting_metadata": "created_at_after",
        "calendar_events": "updated_at__gte",
    }

    @pytest.mark.parametrize("endpoint", sorted(INCREMENTAL_PARAMS))
    def test_incremental_sync_with_watermark_sends_iso_filter(self, endpoint: str) -> None:
        result = _drive(
            endpoint,
            [_page({"next": None, "previous": None, "results": [{"id": "r1"}]})],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC),
        )

        assert result.requests[0].param(self.INCREMENTAL_PARAMS[endpoint]) == "2026-01-15T10:30:00Z"


class TestRecallAIPaginationAndResume:
    def test_fresh_run_follows_next_urls_and_saves_state_per_page(self) -> None:
        page2 = f"{BASE_URL}/api/v1/recording/?cursor=page2"
        page3 = f"{BASE_URL}/api/v1/recording/?cursor=page3"
        responses = [
            _page({"next": page2, "previous": None, "results": [{"id": "r1"}]}),
            _page({"next": page3, "previous": None, "results": [{"id": "r2"}]}),
            _page({"next": None, "previous": page2, "results": [{"id": "r3"}]}),
        ]

        result = _drive("recordings", responses)

        assert result.urls == [f"{BASE_URL}/api/v1/recording/", page2, page3]
        assert [row["id"] for row in result.rows] == ["r1", "r2", "r3"]
        assert result.saved_states == [
            RecallAIResumeConfig(next_url=page2),
            RecallAIResumeConfig(next_url=page3),
        ]

    def test_resume_starts_at_saved_next_url(self) -> None:
        saved_url = f"{BASE_URL}/api/v1/recording/?cursor=saved"

        result = _drive(
            "recordings",
            [_page({"next": None, "previous": None, "results": [{"id": "r9"}]})],
            resume_state=RecallAIResumeConfig(next_url=saved_url),
        )

        assert result.urls == [saved_url]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _drive("recordings", [_page({"next": None, "previous": None, "results": [{"id": "r9"}]})])

        assert result.urls == [f"{BASE_URL}/api/v1/recording/"]


class TestRecallAICredentialScrubbing:
    @pytest.mark.parametrize(
        ("endpoint", "body", "expected_rows"),
        [
            (
                "calendars",
                {
                    "next": None,
                    "previous": None,
                    "results": [
                        {
                            "id": "cal-1",
                            "platform": "google_calendar",
                            "oauth_client_id": "client-id",
                            "oauth_client_secret": "super-secret",
                            "oauth_refresh_token": "refresh-token",
                            "status": "connected",
                        }
                    ],
                },
                [{"id": "cal-1", "platform": "google_calendar", "oauth_client_id": "client-id", "status": "connected"}],
            ),
            (
                "desktop_sdk_uploads",
                {
                    "next": None,
                    "previous": None,
                    "results": [
                        {
                            "id": "upl-1",
                            "status": {"code": "complete", "sub_code": None, "updated_at": "2026-02-01T09:00:00Z"},
                            "recording_id": "rec-1",
                            "upload_token": "fake-upload-token",
                            "created_at": "2026-02-01T08:00:00Z",
                        }
                    ],
                },
                [
                    {
                        "id": "upl-1",
                        "status": {"code": "complete", "sub_code": None, "updated_at": "2026-02-01T09:00:00Z"},
                        "recording_id": "rec-1",
                        "created_at": "2026-02-01T08:00:00Z",
                    }
                ],
            ),
            # A bare JSON array with no pagination envelope. The platform objects nest the
            # credentials, and the platform a connection does not use is null.
            (
                "meeting_direct_connects",
                [
                    {
                        "id": "mdc-zoom",
                        "zoom_rtms": {
                            "meeting_uuid": "meeting-uuid-1",
                            "rtms_stream_id": "stream-1",
                            "server_urls": "wss://rtms.zoom.example.com",
                            "signature": "fake-signature",
                        },
                        "google_meet_media_api": None,
                    },
                    {
                        "id": "mdc-meet",
                        "zoom_rtms": None,
                        "google_meet_media_api": {"space_name": "spaces/abc", "access_token": "fake-access-token"},
                    },
                ],
                [
                    {
                        "id": "mdc-zoom",
                        "zoom_rtms": {
                            "meeting_uuid": "meeting-uuid-1",
                            "rtms_stream_id": "stream-1",
                            "server_urls": "wss://rtms.zoom.example.com",
                        },
                        "google_meet_media_api": None,
                    },
                    {"id": "mdc-meet", "zoom_rtms": None, "google_meet_media_api": {"space_name": "spaces/abc"}},
                ],
            ),
        ],
    )
    def test_credentials_never_reach_the_warehouse(
        self, endpoint: str, body: Any, expected_rows: list[dict[str, Any]]
    ) -> None:
        result = _drive(endpoint, [_page(body)])

        assert len(result.urls) == 1
        assert result.rows == expected_rows


class TestRecallAIUsage:
    TODAY = date(2026, 3, 10)

    def _drive_usage(self, days: int, **inputs: Any) -> DriveResult:
        script = [_page({"bot_total": float(index * 60)}) for index in range(days)]
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.recall_ai._utc_today",
            return_value=self.TODAY,
        ):
            return _drive("usage", script, **inputs)

    def test_incremental_run_rereads_restated_days_and_requests_one_utc_day_each(self) -> None:
        result = self._drive_usage(5, incremental_field="date", db_incremental_field_last_value=date(2026, 3, 9))

        assert result.params("start") == [
            "2026-03-06T00:00:00Z",
            "2026-03-07T00:00:00Z",
            "2026-03-08T00:00:00Z",
            "2026-03-09T00:00:00Z",
            "2026-03-10T00:00:00Z",
        ]
        assert result.params("end") == [
            "2026-03-07T00:00:00Z",
            "2026-03-08T00:00:00Z",
            "2026-03-09T00:00:00Z",
            "2026-03-10T00:00:00Z",
            "2026-03-11T00:00:00Z",
        ]
        assert result.rows[0] == {"date": "2026-03-06", "bot_total": 0.0}
        assert result.rows[-1] == {"date": "2026-03-10", "bot_total": 240.0}
        assert result.saved_states[-1] == RecallAIResumeConfig(next_date="2026-03-10")
        assert result.response is not None and result.response.sort_mode == "asc"

    def test_first_run_backfills_a_bounded_window(self) -> None:
        result = self._drive_usage(USAGE_BACKFILL_DAYS + 1)

        assert len(result.requests) == USAGE_BACKFILL_DAYS + 1
        assert result.rows[-1]["date"] == "2026-03-10"

    def test_resume_starts_at_saved_day(self) -> None:
        result = self._drive_usage(2, resume_state=RecallAIResumeConfig(next_date="2026-03-09"))

        assert [row["date"] for row in result.rows] == ["2026-03-09", "2026-03-10"]


class TestRecallAIHelpers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 1, 15, 10, 30, 45, tzinfo=UTC), "2026-01-15T10:30:45Z"),
            # Naive datetimes from the warehouse watermark are UTC.
            (datetime(2026, 1, 15, 10, 30, 45), "2026-01-15T10:30:45Z"),
            (date(2026, 1, 15), "2026-01-15T00:00:00Z"),
            ("2026-01-15T10:30:45Z", "2026-01-15T10:30:45Z"),
            (None, None),
        ],
    )
    def test_to_iso8601(self, value: Any, expected: str | None) -> None:
        assert _to_iso8601(value) == expected

    def test_unknown_region_raises_before_any_request(self) -> None:
        with pytest.raises(ValueError, match="Unknown Recall.ai region"):
            base_url_for_region("us-central-99")
