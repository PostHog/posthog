from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs import twelve_labs
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.settings import TWELVE_LABS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.twelve_labs import (
    TwelveLabsResumeConfig,
    _build_params,
    _format_incremental_value,
    get_rows,
    twelve_labs_source,
    validate_credentials,
)

logger = structlog.get_logger()


class FakeResumableManager:
    """Minimal ResumableSourceManager stand-in that records saved state in memory."""

    def __init__(self, initial: TwelveLabsResumeConfig | None = None) -> None:
        self.state = initial
        self.saved: list[TwelveLabsResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> TwelveLabsResumeConfig | None:
        return self.state

    def save_state(self, data: TwelveLabsResumeConfig) -> None:
        self.saved.append(data)


def _page(rows: list[dict[str, Any]], page: int, total_page: int) -> dict[str, Any]:
    return {"data": rows, "page_info": {"page": page, "total_page": total_page, "limit_per_page": 50}}


def _mock_response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = payload
    response.text = ""
    return response


def _session_returning(pages: list[dict[str, Any]]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = [_mock_response(p) for p in pages]
    return session


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        # A wrong RFC 3339 shape (e.g. a +00:00 offset) breaks the server-side created_at/updated_at
        # filter, so the exact string matters.
        assert _format_incremental_value(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_incremental_value(datetime(2026, 3, 4, tzinfo=UTC))


class TestBuildParams:
    def test_incremental_sets_filter_and_ascending_sort(self) -> None:
        params = _build_params(
            TWELVE_LABS_ENDPOINTS["indexes"],
            page=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["sort_by"] == "updated_at"
        assert params["sort_option"] == "asc"
        assert params["updated_at"] == "2026-03-04T00:00:00.000Z"
        assert params["page_limit"] == twelve_labs.PAGE_LIMIT

    def test_incremental_first_sync_has_no_filter_value(self) -> None:
        # No watermark yet: sort ascending but don't emit a filter param, else we'd send an empty value.
        params = _build_params(
            TWELVE_LABS_ENDPOINTS["tasks"],
            page=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert params["sort_by"] == "updated_at"
        assert "updated_at" not in params

    def test_full_refresh_sorts_by_stable_creation_field(self) -> None:
        # Full refresh must still pass an explicit ascending sort on a stable field so page
        # boundaries don't skip or duplicate rows if the library grows mid-sync.
        params = _build_params(
            TWELVE_LABS_ENDPOINTS["videos"],
            page=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["sort_by"] == "created_at"
        assert params["sort_option"] == "asc"
        assert not any(k in params for k in ("created_at", "updated_at"))


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response({}, status_code=status_code)
        with patch.object(twelve_labs, "make_tracked_session", return_value=session):
            ok, returned_status = validate_credentials("tlk_key")
        assert ok is expected
        # The caller relies on the status code to tell a rejected key from a transient outage.
        assert returned_status == status_code

    def test_network_error_reports_no_status(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(twelve_labs, "make_tracked_session", return_value=session):
            ok, returned_status = validate_credentials("tlk_key")
        assert ok is False
        assert returned_status is None

    def test_credentialed_session_redacts_key_and_refuses_redirects(self) -> None:
        # The x-api-key value must never reach tracked telemetry, and a 30x must not replay it to
        # another host, so validation builds the session with both guards on.
        session = MagicMock()
        session.get.return_value = _mock_response({}, status_code=200)
        with patch.object(twelve_labs, "make_tracked_session", return_value=session) as make_session:
            validate_credentials("tlk_key")
        make_session.assert_called_once_with(redact_values=("tlk_key",), allow_redirects=False)


class TestGetRowsPagination:
    def test_walks_pages_until_total_page(self) -> None:
        pages = [
            _page([{"_id": "a"}], page=1, total_page=2),
            _page([{"_id": "b"}], page=2, total_page=2),
        ]
        session = _session_returning(pages)
        manager = FakeResumableManager()
        with patch.object(twelve_labs, "make_tracked_session", return_value=session):
            batches = list(get_rows("tlk", "indexes", logger, manager))  # type: ignore[arg-type]

        assert [row["_id"] for batch in batches for row in batch] == ["a", "b"]
        assert session.get.call_count == 2

    def test_saves_resume_state_after_each_page_but_not_on_last(self) -> None:
        # State is saved after yielding a page (so a crash re-yields, not skips) and only while more
        # pages remain, so we never bookmark past the end of the list.
        pages = [
            _page([{"_id": "a"}], page=1, total_page=2),
            _page([{"_id": "b"}], page=2, total_page=2),
        ]
        session = _session_returning(pages)
        manager = FakeResumableManager()
        with patch.object(twelve_labs, "make_tracked_session", return_value=session):
            list(get_rows("tlk", "indexes", logger, manager))  # type: ignore[arg-type]

        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self) -> None:
        session = _session_returning([_page([{"_id": "b"}], page=2, total_page=2)])
        manager = FakeResumableManager(TwelveLabsResumeConfig(next_page=2))
        with patch.object(twelve_labs, "make_tracked_session", return_value=session):
            list(get_rows("tlk", "indexes", logger, manager))  # type: ignore[arg-type]

        # Only page 2 is fetched — the resume skips page 1.
        requested_url = session.get.call_args_list[0].args[0]
        assert "page=2" in requested_url
        assert session.get.call_count == 1


class TestFanOut:
    def test_injects_parent_index_id_into_every_video_row(self) -> None:
        # /indexes returns two indexes, each with one video page. The parent index_id must land on
        # every row so the [index_id, _id] primary key stays unique table-wide.
        pages = [
            _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),  # /indexes
            _page([{"_id": "v1"}], page=1, total_page=1),  # idx1 videos
            _page([{"_id": "v2"}], page=1, total_page=1),  # idx2 videos
        ]
        session = _session_returning(pages)
        manager = FakeResumableManager()
        with patch.object(twelve_labs, "make_tracked_session", return_value=session):
            batches = list(get_rows("tlk", "videos", logger, manager))  # type: ignore[arg-type]

        rows = [row for batch in batches for row in batch]
        assert {(r["index_id"], r["_id"]) for r in rows} == {("idx1", "v1"), ("idx2", "v2")}

    def test_resumes_into_bookmarked_index(self) -> None:
        # Bookmarked on idx2: idx1's videos must not be re-fetched.
        pages = [
            _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),  # /indexes
            _page([{"_id": "v2"}], page=1, total_page=1),  # idx2 videos
        ]
        session = _session_returning(pages)
        manager = FakeResumableManager(TwelveLabsResumeConfig(next_page=1, index_id="idx2"))
        with patch.object(twelve_labs, "make_tracked_session", return_value=session):
            batches = list(get_rows("tlk", "videos", logger, manager))  # type: ignore[arg-type]

        rows = [row for batch in batches for row in batch]
        assert {r["index_id"] for r in rows} == {"idx2"}


class TestTwelveLabsSourceResponse:
    @parameterized.expand([("indexes", ["_id"]), ("tasks", ["_id"]), ("videos", ["index_id", "_id"])])
    def test_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = twelve_labs_source("tlk", endpoint, logger, FakeResumableManager())  # type: ignore[arg-type]
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]
