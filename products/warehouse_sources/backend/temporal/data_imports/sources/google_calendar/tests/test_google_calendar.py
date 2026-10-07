import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.member_accounts import (
    ALL_ACCOUNTS_UNREADABLE,
    MemberAccount,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.google_calendar import (
    GoogleCalendarCursor,
    events_source,
)

REQUEST_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.google_calendar"
    ".google_workspace_request"
)

ADA = MemberAccount(account_id="ada", access_token="ada-token")
GRACE = MemberAccount(account_id="grace", access_token="grace-token")
NOW = "2026-10-07T12:00:00.000Z"


def _event(event_id: str, updated: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": event_id,
        "status": "confirmed",
        "created": "2026-09-01T09:00:00.000Z",
        "updated": updated,
        "summary": "Secret project sync",
        "start": {"dateTime": "2026-10-06T10:00:00+02:00"},
        "end": {"dateTime": "2026-10-06T10:45:00+02:00"},
        "attendees": [
            {"email": "ada@example.com", "self": True, "responseStatus": "accepted"},
            {"email": "grace@example.com", "responseStatus": "declined"},
        ],
        **overrides,
    }


def _response(status_code: int, body: dict[str, Any] | None = None) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body or {}).encode()
    return response


def _run(
    accounts: list[MemberAccount], request: MagicMock, cursor: GoogleCalendarCursor | None = None
) -> tuple[list[dict[str, Any]], list[GoogleCalendarCursor]]:
    staged: list[GoogleCalendarCursor] = []
    with patch(REQUEST_PATCH, request), time_machine.travel(NOW, tick=False):
        response = events_source(accounts, cursor, staged.append, MagicMock())
        rows = [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]
        assert response.on_complete is not None
        response.on_complete()
    return rows, staged


def _params(request: MagicMock) -> list[tuple[str, dict[str, Any]]]:
    return [(call.kwargs["account_id"], call.kwargs["params"]) for call in request.call_args_list]


class TestEventsSource:
    def test_first_sync_backfills_a_year_and_follows_pages(self) -> None:
        request = MagicMock(
            side_effect=[
                _response(200, {"items": [_event("a", "2026-10-01T08:00:00.000Z")], "nextPageToken": "page-2"}),
                _response(200, {"items": [_event("b", "2026-10-05T08:00:00.000Z")]}),
            ]
        )

        rows, staged = _run([ADA], request)

        assert [row["id"] for row in rows] == ["a", "b"]
        first, second = _params(request)
        assert first[1]["timeMin"] == "2025-10-07T12:00:00.000Z"
        assert first[1]["timeMax"] == NOW
        assert "updatedMin" not in first[1]
        assert second[1]["pageToken"] == "page-2"
        assert staged == [
            GoogleCalendarCursor(updated_at={"ada": "2026-10-05T08:00:00.000Z"}, synced_until={"ada": NOW})
        ]

    def test_later_sync_reads_new_occurrences_and_edits_for_a_known_account_only(self) -> None:
        request = MagicMock(side_effect=lambda *args, **kwargs: _response(200, {"items": []}))
        cursor = GoogleCalendarCursor(
            updated_at={"ada": "2026-10-05T08:00:00.000Z"}, synced_until={"ada": "2026-10-07T06:00:00.000Z"}
        )

        _, staged = _run([ADA, GRACE], request, cursor)

        ada_calls = [params for account_id, params in _params(request) if account_id == "ada"]
        grace_calls = [params for account_id, params in _params(request) if account_id == "grace"]
        assert [(p["timeMin"], p.get("updatedMin")) for p in ada_calls] == [
            ("2026-10-07T06:00:00.000Z", None),
            ("2025-10-07T12:00:00.000Z", "2026-10-05T08:00:00.000Z"),
        ]
        # Grace connected after the last sync, so she gets the whole backfill.
        assert [(p["timeMin"], p.get("updatedMin")) for p in grace_calls] == [("2025-10-07T12:00:00.000Z", None)]
        # An account with nothing new keeps its edit position, and one with no events still gets one.
        assert staged[0].updated_at == {"ada": "2026-10-05T08:00:00.000Z", "grace": NOW}

    def test_an_expired_edit_position_falls_back_to_the_full_window(self) -> None:
        request = MagicMock(
            side_effect=[
                _response(200, {"items": []}),
                _response(410),
                _response(200, {"items": [_event("a", "2026-10-06T08:00:00.000Z")]}),
            ]
        )
        cursor = GoogleCalendarCursor(updated_at={"ada": "2026-01-01T00:00:00.000Z"}, synced_until={"ada": NOW})

        rows, _ = _run([ADA], request, cursor)

        assert [row["id"] for row in rows] == ["a"]
        assert "updatedMin" not in _params(request)[-1][1]

    @parameterized.expand([(401, {}), (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}})])
    def test_an_account_google_refuses_does_not_block_the_others(self, status: int, body: dict[str, Any]) -> None:
        request = MagicMock(
            side_effect=lambda *args, **kwargs: (
                _response(status, body)
                if kwargs["account_id"] == "grace"
                else _response(200, {"items": [_event("a", "2026-10-06T08:00:00.000Z")]})
            )
        )

        rows, staged = _run([ADA, GRACE], request)

        assert [(row["account_id"], row["id"]) for row in rows] == [("ada", "a")]
        assert staged[0].synced_until == {"ada": NOW}

    def test_every_account_refused_fails_the_sync(self) -> None:
        request = MagicMock(side_effect=lambda *args, **kwargs: _response(401))

        with pytest.raises(ValueError, match=ALL_ACCOUNTS_UNREADABLE):
            _run([ADA, GRACE], request)

    def test_a_quota_error_fails_the_sync_instead_of_skipping_the_account(self) -> None:
        body = {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}
        request = MagicMock(side_effect=lambda *args, **kwargs: _response(403, body))

        with pytest.raises(HTTPError):
            _run([ADA], request)

    def test_rows_carry_meeting_shape_without_titles_or_attendee_addresses(self) -> None:
        all_day = _event(
            "b", "2026-10-06T08:00:00.000Z", start={"date": "2026-10-06"}, end={"date": "2026-10-07"}, attendees=None
        )
        request = MagicMock(
            return_value=_response(200, {"items": [_event("a", "2026-10-06T08:00:00.000Z", hangoutLink="x"), all_day]})
        )

        rows, _ = _run([ADA], request)

        assert "ada@example.com" not in json.dumps(rows, default=str)
        assert "Secret project sync" not in json.dumps(rows, default=str)
        assert {key: rows[0][key] for key in ("duration_minutes", "attendee_count", "response_status")} == {
            "duration_minutes": 45,
            "attendee_count": 2,
            "response_status": "accepted",
        }
        assert rows[0]["has_video_call"] is True
        assert (rows[1]["is_all_day"], rows[1]["duration_minutes"], rows[1]["attendee_count"]) == (True, 1440, 0)
