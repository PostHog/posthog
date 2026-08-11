import json
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock

from requests import RequestException, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.close import search as close_search
from products.warehouse_sources.backend.temporal.data_imports.sources.close.close import (
    close_search_source,
    close_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.close.search import (
    CloseCursorExpiredError,
    CloseSearchError,
    build_search_body,
    fetch_custom_field_selectors,
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

    def __init__(self, pages: list[Response], get_pages: Optional[list[Any]] = None) -> None:
        self._pages = list(pages)
        self._get_pages = list(get_pages or [])
        self.bodies: list[dict[str, Any]] = []
        self.get_params: list[dict[str, Any]] = []

    def post(self, url: str, json: dict[str, Any], timeout: int) -> Response:  # noqa: A002
        self.bodies.append(json)
        if not self._pages:
            raise AssertionError(f"unexpected extra search request: {json}")
        return self._pages.pop(0)

    def get(self, url: str, params: dict[str, Any], timeout: int) -> Response:
        self.get_params.append(params)
        page = self._get_pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


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


class TestBuildSearchBody:
    def test_anchored_body_filters_and_sorts_on_the_cursor_field(self) -> None:
        body = build_search_body("contact", ["id"], "date_updated", "2024-01-02T03:04:05+00:00", limit=50)

        condition = body["query"]["queries"][1]
        assert condition["field"] == {
            "type": "regular_field",
            "object_type": "contact",
            "field_name": "date_updated",
        }
        # `on_or_after` (not `after`) is what makes re-reading the anchor safe rather than lossy.
        assert condition["condition"] == {
            "type": "moment_range",
            "on_or_after": {"type": "fixed_utc", "value": "2024-01-02T03:04:05+00:00"},
        }
        assert body["sort"][0]["direction"] == "asc"
        assert body["sort"][0]["field"]["field_name"] == "date_updated"
        assert body["_fields"] == {"contact": ["id"]}
        assert body["_limit"] == 50
        assert "cursor" not in body

    def test_unanchored_body_has_no_date_filter(self) -> None:
        body = build_search_body("lead", ["id"], "date_created", None)
        assert [q["type"] for q in body["query"]["queries"]] == ["object_type"]

    def test_cursor_is_sent_when_stepping_over_a_plateau(self) -> None:
        body = build_search_body("lead", ["id"], "date_created", "2024-01-01T00:00:00+00:00", page_cursor="abc")
        assert body["cursor"] == "abc"


class TestIterSearchRows:
    def test_walk_reads_every_row_exactly_once(self) -> None:
        # Each keyset page re-reads the rows tied to the anchor because `on_or_after` is
        # inclusive; they must not be emitted twice.
        close = FakeClose([_row(f"c{i}", f"2024-01-{i:02d}T00:00:00+00:00") for i in range(1, 8)])

        rows = _walk(close)

        assert [row["id"] for row in rows] == [f"c{i}" for i in range(1, 8)]
        # Every request after the first moves the anchor strictly forward, so no request ever
        # reaches for a deep offset and none of them repeat.
        anchors = [_anchor_of(body) for body in close.bodies]
        assert anchors[0] is None
        assert anchors[1:] == sorted(set(cast(list[str], anchors[1:])))

    def test_short_page_ends_the_walk(self) -> None:
        session = FakeSession([_response({"data": [_row("c1", "2024-01-01T00:00:00+00:00")]})])

        assert [row["id"] for row in _walk(session)] == ["c1"]
        assert len(session.bodies) == 1

    def test_rows_sharing_one_timestamp_are_paged_with_the_cursor(self) -> None:
        # The keyset filter cannot advance across a run of identical timestamps, so without the
        # cursor fallback this walk would re-request the same page forever.
        tied = "2024-01-01T00:00:00+00:00"
        close = FakeClose(
            [_row(f"c{i}", tied) for i in range(1, 6)] + [_row("c6", "2024-02-01T00:00:00+00:00")],
        )

        rows = _walk(close)

        assert [row["id"] for row in rows] == ["c1", "c2", "c3", "c4", "c5", "c6"]
        assert any(body.get("cursor") for body in close.bodies)

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

    def test_start_anchor_is_applied_to_the_first_request(self) -> None:
        session = FakeSession([_response({"data": [_row("c1", "2024-06-01T00:00:00+00:00")]})])

        _walk(session, start_anchor="2024-05-01T00:00:00+00:00")

        assert _anchor_of(session.bodies[0]) == "2024-05-01T00:00:00+00:00"

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


class TestFetchCustomFieldSelectors:
    def test_selectors_are_built_from_every_page(self) -> None:
        session = FakeSession(
            [],
            get_pages=[
                _response({"data": [{"id": "cf_a"}], "has_more": True}),
                _response({"data": [{"id": "cf_b"}], "has_more": False}),
            ],
        )

        selectors = fetch_custom_field_selectors(cast(Any, session), BASE_URL, "contact", MagicMock())

        assert selectors == ["custom.cf_a", "custom.cf_b"]

    @pytest.mark.parametrize(
        "failure",
        [RequestException("403 Forbidden"), ValueError("not json")],
        ids=["no_access", "bad_payload"],
    )
    def test_failure_falls_back_to_standard_fields(self, failure: Exception) -> None:
        # A key without custom-field access should still sync the standard columns.
        session = FakeSession([], get_pages=[failure])

        assert fetch_custom_field_selectors(cast(Any, session), BASE_URL, "contact", MagicMock()) == []


class TestSearchSourceWiring:
    @pytest.mark.parametrize("endpoint", ["Leads", "Contacts"])
    def test_capped_endpoints_read_through_advanced_filtering(self, endpoint: str, monkeypatch: Any) -> None:
        # Guards the routing itself: if these fall back to /lead/ and /contact/, they silently
        # truncate again at Close's `_skip` cap.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        session = FakeSession([_response({"data": []})], get_pages=[_response({"data": []})])
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.close.close._make_search_session",
            lambda _api_key: session,
        )

        response = close_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=None,
            logger=MagicMock(),
        )
        list(cast(Any, response.items()))

        assert session.bodies[0]["query"]["queries"][0]["object_type"] == endpoint.rstrip("s").lower()

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
        session = FakeSession([_response({"data": []})], get_pages=[_response({"data": []})])
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.close.close._make_search_session",
            lambda _api_key: session,
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
