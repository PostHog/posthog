from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.fathom._config import FathomSourceConfig
from products.warehouse_sources.sources.fathom.fathom import FathomResumeConfig
from products.warehouse_sources.sources.fathom.source import FathomSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


def _driver() -> SourceDriver:
    return SourceDriver(FathomSource(), FathomSourceConfig(api_key="fathom-key"))


def _meeting(recording_id: int, **extra: Any) -> dict[str, Any]:
    return {
        "recording_id": recording_id,
        "title": f"Meeting {recording_id}",
        "created_at": "2026-03-01T17:01:30Z",
        "transcript_language": "en",
        "recorded_by": {"name": "Alex Doe", "email": "alex@example.com", "email_domain": "example.com", "team": None},
        **extra,
    }


def _page(items: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"limit": 10, "next_cursor": next_cursor, "items": items})


class TestPagination:
    def test_follows_next_cursor_to_the_terminal_page_and_saves_the_cursor_first(self) -> None:
        result = _driver().run(
            "meetings",
            [_page([_meeting(1), _meeting(2)], "cursor-2"), _page([_meeting(3)], None)],
        )

        assert result.raised is None
        assert [row["recording_id"] for row in result.rows] == [1, 2, 3]
        assert result.paths == ["/external/v1/meetings", "/external/v1/meetings"]
        assert result.params("cursor") == [None, "cursor-2"]
        # The include flags must ride on every page, not only the first.
        assert result.params("include_action_items") == ["true", "true"]
        assert result.params("include_transcript") == [None, None]
        assert all(request.headers["x-api-key"] == "fathom-key" for request in result.requests)
        assert result.committed_states == [FathomResumeConfig(cursor="cursor-2")]

    def test_resumes_from_the_saved_cursor(self) -> None:
        result = _driver().run(
            "teams",
            [_page([{"name": "Sales", "created_at": "2023-11-10T12:00:00Z"}], None)],
            resume_state=FathomResumeConfig(cursor="cursor-5"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cursor-5"]
        assert result.rows == [{"name": "Sales", "created_at": "2023-11-10T12:00:00Z"}]


class TestIncrementalRequests:
    @parameterized.expand(
        [
            ("watermark_as_utc_datetime", True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            (
                "watermark_in_another_timezone",
                True,
                datetime(2026, 1, 2, 5, 4, 5, tzinfo=timezone(timedelta(hours=2))),
                "2026-01-02T03:04:05Z",
            ),
            ("watermark_as_naive_datetime", True, datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            ("first_incremental_sync_reads_everything", True, None, None),
            ("full_refresh_ignores_a_watermark", False, datetime(2026, 1, 2, tzinfo=UTC), None),
        ]
    )
    def test_created_after_filter(
        self, _name: str, incremental: bool, watermark: datetime | None, expected: str | None
    ) -> None:
        result = _driver().run(
            "meetings",
            [_page([_meeting(1)], "cursor-2"), _page([], None)],
            incremental_field="created_at",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.params("created_after") == [expected, expected]


class TestHeavyContentTables:
    @parameterized.expand(
        [
            (
                "meeting_summaries",
                "include_summary",
                {"default_summary": {"template_name": "general", "markdown_formatted": "## Summary"}},
            ),
            (
                "meeting_transcripts",
                "include_transcript",
                {
                    "transcript": [
                        {"speaker": {"display_name": "Alex Doe"}, "text": "Hello.", "timestamp": "00:00:05"},
                    ]
                },
            ),
        ]
    )
    def test_requests_only_its_own_content_and_keeps_only_its_columns(
        self, schema_name: str, include_flag: str, content: dict[str, Any]
    ) -> None:
        result = _driver().run(schema_name, [_page([_meeting(7, **content)], None)])

        assert result.raised is None
        assert result.params(include_flag) == ["true"]
        assert result.params("include_action_items") == [None]
        row = result.rows[0]
        assert row["recording_id"] == 7
        assert row["created_at"] == "2026-03-01T17:01:30Z"
        for key, value in content.items():
            assert row[key] == value
        assert "title" not in row
        assert "recorded_by" not in row

    def test_summary_row_keeps_a_null_summary(self) -> None:
        result = _driver().run("meeting_summaries", [_page([_meeting(8, default_summary=None)], None)])

        assert result.raised is None
        assert result.rows == [{"recording_id": 8, "created_at": "2026-03-01T17:01:30Z", "default_summary": None}]
