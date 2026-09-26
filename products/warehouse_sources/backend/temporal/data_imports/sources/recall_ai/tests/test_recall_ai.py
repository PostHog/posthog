import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recall_ai.recall_ai import (
    RecallAIResumeConfig,
    _to_iso8601,
    base_url_for_region,
    recall_ai_source,
)

BASE_URL = "https://us-east-1.recall.ai"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = f"{BASE_URL}/api/v1/recording/"
    return resp


def _drive(
    endpoint: str,
    manager: MagicMock,
    responses: list[Response],
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Drive ``recall_ai_source`` with a mocked HTTP session.

    Returns ``(sent_urls, sent_params, rows)``. Params are captured as shallow copies at
    send-time because the paginator mutates the Request object in place between pages.
    """
    sent_urls: list[str] = []
    sent_params: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_urls.append(request.url)
        sent_params.append(dict(request.params or {}))
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    ) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        source_response = recall_ai_source(
            api_key="test-key",
            region="us-east-1",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        )
        rows = [row for page in source_response.items() for row in page]
        return sent_urls, sent_params, rows


def _manager(can_resume: bool = False) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    return manager


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
        _, sent_params, _ = _drive(
            endpoint,
            _manager(),
            [_make_http_response({"next": None, "previous": None, "results": [{"id": "r1"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC),
        )

        assert sent_params[0][self.INCREMENTAL_PARAMS[endpoint]] == "2026-01-15T10:30:00Z"

    @pytest.mark.parametrize("endpoint", sorted(INCREMENTAL_PARAMS))
    @pytest.mark.parametrize(
        ("should_use_incremental_field", "last_value"),
        [
            # First incremental sync has no watermark yet and must go out unfiltered.
            (True, None),
            # Full refresh must ignore a stale watermark.
            (False, datetime(2026, 1, 15, tzinfo=UTC)),
        ],
    )
    def test_filter_omitted_without_active_watermark(
        self, endpoint: str, should_use_incremental_field: bool, last_value: Any
    ) -> None:
        _, sent_params, _ = _drive(
            endpoint,
            _manager(),
            [_make_http_response({"next": None, "previous": None, "results": [{"id": "r1"}]})],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert self.INCREMENTAL_PARAMS[endpoint] not in sent_params[0]

    def test_bots_request_uses_cursor_pagination_and_no_time_filter(self) -> None:
        # Without use_cursor the bot list paginates by page number, which skips or repeats
        # rows when bots are created mid-walk. Bots also have no server-side created-at
        # filter, so no watermark param may ever be attached.
        _, sent_params, _ = _drive(
            "bots",
            _manager(),
            [_make_http_response({"next": None, "previous": None, "results": [{"id": "b1"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert sent_params[0]["use_cursor"] == "true"
        assert "join_at_after" not in sent_params[0]
        assert "created_at_after" not in sent_params[0]


class TestRecallAIPaginationAndResume:
    def test_fresh_run_follows_next_urls_and_saves_state_per_page(self) -> None:
        manager = _manager()
        page2 = f"{BASE_URL}/api/v1/recording/?cursor=page2"
        page3 = f"{BASE_URL}/api/v1/recording/?cursor=page3"
        responses = [
            _make_http_response({"next": page2, "previous": None, "results": [{"id": "r1"}]}),
            _make_http_response({"next": page3, "previous": None, "results": [{"id": "r2"}]}),
            _make_http_response({"next": None, "previous": page2, "results": [{"id": "r3"}]}),
        ]

        sent_urls, _, rows = _drive("recordings", manager, responses)

        assert sent_urls == [f"{BASE_URL}/api/v1/recording/", page2, page3]
        assert [row["id"] for row in rows] == ["r1", "r2", "r3"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            RecallAIResumeConfig(next_url=page2),
            RecallAIResumeConfig(next_url=page3),
        ]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _manager()

        _drive(
            "recordings",
            manager,
            [_make_http_response({"next": None, "previous": None, "results": [{"id": "r1"}]})],
        )

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    def test_resume_starts_at_saved_next_url(self) -> None:
        manager = _manager(can_resume=True)
        saved_url = f"{BASE_URL}/api/v1/recording/?cursor=saved"
        manager.load_state.return_value = RecallAIResumeConfig(next_url=saved_url)

        sent_urls, _, _ = _drive(
            "recordings",
            manager,
            [_make_http_response({"next": None, "previous": None, "results": [{"id": "r9"}]})],
        )

        assert sent_urls == [saved_url]
        manager.load_state.assert_called_once()


class TestRecallAICalendarScrubbing:
    def test_oauth_secrets_never_reach_the_warehouse(self) -> None:
        calendar = {
            "id": "cal-1",
            "platform": "google_calendar",
            "oauth_client_id": "client-id",
            "oauth_client_secret": "super-secret",
            "oauth_refresh_token": "refresh-token",
            "status": "connected",
        }

        _, _, rows = _drive(
            "calendars",
            _manager(),
            [_make_http_response({"next": None, "previous": None, "results": [calendar]})],
        )

        assert rows == [
            {
                "id": "cal-1",
                "platform": "google_calendar",
                "oauth_client_id": "client-id",
                "status": "connected",
            }
        ]


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
