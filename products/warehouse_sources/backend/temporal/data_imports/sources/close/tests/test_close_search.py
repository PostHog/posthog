import json
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.close import search as close_search
from products.warehouse_sources.backend.temporal.data_imports.sources.close.close import close_search_source
from products.warehouse_sources.backend.temporal.data_imports.sources.close.search import (
    CloseCursorExpiredError,
    CloseSearchError,
    iter_search_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BASE_URL = "https://api.close.com/api/v1"


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _row(row_id: str, date_created: str) -> dict[str, Any]:
    return {"id": row_id, "date_created": date_created}


class FakeSession:
    """Stands in for the tracked HTTP session, recording the search bodies it was sent."""

    def __init__(self, pages: list[Response]) -> None:
        self._pages = list(pages)
        self.bodies: list[dict[str, Any]] = []

    def post(self, url: str, json: dict[str, Any], timeout: int) -> Response:  # noqa: A002
        self.bodies.append(json)
        if not self._pages:
            raise AssertionError(f"unexpected extra search request: {json}")
        return self._pages.pop(0)


def _anchor_of(body: dict[str, Any]) -> Optional[str]:
    for query in body["query"]["queries"]:
        if query["type"] == "field_condition":
            return cast(str, query["condition"]["on_or_after"]["value"])
    return None


class FakeClose:
    """Answers `/data/search/` out of a fixed, ascending dataset the way Close does.

    Cursor-less requests re-run the `on_or_after` filter from the top; a cursor resumes where
    the page that handed it out left off. Faithful enough that the walker's paging decisions —
    not the test's assumptions about them — are what's under test.
    """

    def __init__(self, rows: list[dict[str, Any]], expire_next_cursor: bool = False) -> None:
        self.rows = rows
        self.bodies: list[dict[str, Any]] = []
        self._cursors: dict[str, int] = {}
        self._issued = 0
        self._expire_next_cursor = expire_next_cursor

    def post(self, url: str, json: dict[str, Any], timeout: int) -> Response:  # noqa: A002
        self.bodies.append(json)
        cursor = json.get("cursor")

        if cursor is not None:
            if self._expire_next_cursor:
                self._expire_next_cursor = False
                return _response({"error": "Expired cursor"}, status_code=400)
            start = self._cursors[cursor]
        else:
            anchor = _anchor_of(json)
            start = (
                0
                if anchor is None
                else next((i for i, row in enumerate(self.rows) if row["date_created"] >= anchor), len(self.rows))
            )

        page = self.rows[start : start + json["_limit"]]
        end = start + len(page)
        body: dict[str, Any] = {"data": page, "cursor": None}
        if end < len(self.rows):
            token = f"cur{self._issued}"
            self._issued += 1
            self._cursors[token] = end
            body["cursor"] = token
        return _response(body)


def _walk(session: FakeSession | FakeClose, limit: int = 2, start_anchor: Optional[str] = None) -> list[dict[str, Any]]:
    batches = iter_search_rows(
        session=cast(Any, session),
        base_url=BASE_URL,
        object_type="contact",
        fields=["id", "date_created"],
        cursor_field="date_created",
        start_anchor=start_anchor,
        logger=MagicMock(),
        limit=limit,
    )
    return [row for batch in batches for row in batch]


class TestIterSearchRows:
    def test_short_page_ends_the_walk(self) -> None:
        session = FakeSession([_response({"data": [_row("c1", "2024-01-01T00:00:00+00:00")]})])

        assert [row["id"] for row in _walk(session)] == ["c1"]
        assert len(session.bodies) == 1

    def test_expired_cursor_reanchors_instead_of_failing_the_sync(self) -> None:
        # A slow Delta write can stall the walk past Close's 30s cursor TTL; the run should
        # recover by re-issuing the query rather than dying.
        tied = "2024-01-01T00:00:00+00:00"
        close = FakeClose(
            [_row(f"c{i}", tied) for i in range(1, 6)] + [_row("c6", "2024-02-01T00:00:00+00:00")],
            expire_next_cursor=True,
        )

        rows = _walk(close)

        assert [row["id"] for row in rows] == ["c1", "c2", "c3", "c4", "c5", "c6"]

    def test_checkpoint_records_the_last_emitted_anchor(self) -> None:
        session = FakeSession(
            [
                _response({"data": [_row("c1", "2024-01-01T00:00:00+00:00"), _row("c2", "2024-01-02T00:00:00+00:00")]}),
                _response({"data": [_row("c2", "2024-01-02T00:00:00+00:00")]}),
            ]
        )
        seen: list[str] = []

        list(
            iter_search_rows(
                session=cast(Any, session),
                base_url=BASE_URL,
                object_type="contact",
                fields=["id"],
                cursor_field="date_created",
                start_anchor=None,
                logger=MagicMock(),
                on_checkpoint=seen.append,
                limit=2,
            )
        )

        assert seen == ["2024-01-02T00:00:00+00:00"]

    def test_rejected_query_surfaces_closes_message(self) -> None:
        session = FakeSession([_response({"field-errors": {"_fields": "unknown field"}}, status_code=400)])

        with pytest.raises(CloseSearchError, match="unknown field"):
            _walk(session)

    @pytest.mark.parametrize(
        ("row", "match"),
        [
            ({"date_created": "2024-01-01T00:00:00+00:00"}, "without an id"),
            ({"id": "c1"}, "without a date_created value"),
        ],
        ids=["missing_id", "missing_cursor_field"],
    )
    def test_malformed_rows_fail_loudly(self, row: dict[str, Any], match: str) -> None:
        # A row the walker can't key or order would otherwise duplicate silently (no id to
        # dedupe the inclusive anchor re-reads on) or re-request the same page forever (no
        # cursor-field value to advance the anchor with).
        session = FakeSession([_response({"data": [row]})])

        with pytest.raises(CloseSearchError, match=match):
            _walk(session)

    def test_expired_cursor_on_a_cursorless_request_is_fatal(self) -> None:
        # The re-anchor recovery only makes sense when a cursor was actually sent; replaying
        # an identical cursor-less request can never succeed, so it must propagate instead of
        # retrying forever.
        session = FakeSession([_response({"error": "Expired cursor"}, status_code=400)])

        with pytest.raises(CloseCursorExpiredError):
            _walk(session)

        assert len(session.bodies) == 1

    def test_endless_single_timestamp_run_aborts_instead_of_looping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # If Close's cursor never terminates a run of identical timestamps, the plateau guard
        # is the only thing standing between the walk and an infinite loop.
        monkeypatch.setattr(close_search, "MAX_PLATEAU_PAGES", 2)
        tied = "2024-01-01T00:00:00+00:00"
        close = FakeClose([_row(f"c{i}", tied) for i in range(1, 13)])

        with pytest.raises(CloseSearchError, match="cannot be paged past"):
            _walk(close)


class TestSearchSourceWiring:
    @pytest.mark.parametrize(
        ("incremental", "field", "last_value", "expected_cursor_field", "expected_anchor"),
        [
            (False, None, "2024-06-01T00:00:00+00:00", "date_created", None),
            (True, "date_updated", "2024-06-01T00:00:00+00:00", "date_updated", "2024-06-01T00:00:00+00:00"),
            (True, "bogus", "2024-06-01T00:00:00+00:00", "date_created", "2024-06-01T00:00:00+00:00"),
            (True, "date_created", None, "date_created", None),
        ],
        ids=["full_refresh_ignores_watermark", "honors_chosen_cursor", "falls_back_to_first_cursor", "no_watermark"],
    )
    def test_starting_anchor_follows_the_incremental_settings(
        self,
        incremental: bool,
        field: Optional[str],
        last_value: Optional[str],
        expected_cursor_field: str,
        expected_anchor: Optional[str],
        monkeypatch: Any,
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        session = FakeSession([_response({"data": []})])
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.close.close._make_session",
            lambda _api_key, **_kwargs: session,
        )

        response = close_search_source(
            api_key="test-key",
            endpoint="Contacts",
            resumable_source_manager=manager,
            logger=MagicMock(),
            db_incremental_field_last_value=last_value,
            should_use_incremental_field=incremental,
            incremental_field=field,
        )
        list(cast(Any, response.items()))

        assert session.bodies[0]["sort"][0]["field"]["field_name"] == expected_cursor_field
        assert _anchor_of(session.bodies[0]) == expected_anchor
