import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs import twelve_labs
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.settings import TWELVE_LABS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.twelve_labs import (
    TwelveLabsResumeConfig,
    _build_params,
    _format_incremental_value,
    twelve_labs_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the twelve_labs module.
TL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.twelve_labs.make_tracked_session"
)


def _page(rows: list[dict[str, Any]], page: int, total_page: int, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = "https://api.twelvelabs.io/v1.3/mock"
    resp.reason = "Error" if status >= 400 else "OK"
    resp._content = json.dumps(
        {"data": rows, "page_info": {"page": page, "total_page": total_page, "limit_per_page": 50}}
    ).encode()
    return resp


def _make_manager(resume_state: TwelveLabsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session, returning (url, params) snapshots captured AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return twelve_labs_source(
        api_key="tlk",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager or _make_manager(),
        **kwargs,
    )


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
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(TL_SESSION_PATCH, return_value=session):
            ok, returned_status = validate_credentials("tlk_key")
        assert ok is expected
        # The caller relies on the status code to tell a rejected key from a transient outage.
        assert returned_status == status_code

    def test_network_error_reports_no_status(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(TL_SESSION_PATCH, return_value=session):
            ok, returned_status = validate_credentials("tlk_key")
        assert ok is False
        assert returned_status is None

    def test_credentialed_session_redacts_key_and_refuses_redirects(self) -> None:
        # The x-api-key value must never reach tracked telemetry, and a 30x must not replay it to
        # another host, so validation builds the session with both guards on.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(TL_SESSION_PATCH, return_value=session) as make_session:
            validate_credentials("tlk_key")
        make_session.assert_called_once_with(redact_values=("tlk_key",), allow_redirects=False)


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_pages_until_total_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_page([{"_id": "a"}], page=1, total_page=2), _page([{"_id": "b"}], page=2, total_page=2)],
        )

        rows = _rows(_source("indexes"))

        assert [r["_id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 2
        assert snapshots[0][0] == "https://api.twelvelabs.io/v1.3/indexes"
        assert snapshots[0][1]["page"] == 1
        assert snapshots[0][1]["page_limit"] == 50
        assert snapshots[1][1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_after_each_page_but_not_on_last(self, MockSession) -> None:
        # State is saved after yielding a page (so a crash re-yields, not skips) and only while more
        # pages remain, so we never bookmark past the end of the list.
        session = MockSession.return_value
        _wire(session, [_page([{"_id": "a"}], page=1, total_page=2), _page([{"_id": "b"}], page=2, total_page=2)])

        manager = _make_manager()
        _rows(_source("indexes", manager=manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [s.next_page for s in saved] == [2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([{"_id": "b"}], page=2, total_page=2)])

        manager = _make_manager(TwelveLabsResumeConfig(next_page=2))
        rows = _rows(_source("indexes", manager=manager))

        # Only page 2 is fetched — the resume skips page 1.
        assert [r["_id"] for r in rows] == ["b"]
        assert session.send.call_count == 1
        assert snapshots[0][1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_applies_server_side_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([{"_id": "a"}], page=1, total_page=1)])

        _rows(
            _source(
                "indexes",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert snapshots[0][1]["sort_by"] == "updated_at"
        assert snapshots[0][1]["sort_option"] == "asc"
        assert snapshots[0][1]["updated_at"] == "2026-03-04T02:58:14.000Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sends_no_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([{"_id": "a"}], page=1, total_page=1)])

        _rows(_source("indexes"))

        assert snapshots[0][1]["sort_by"] == "created_at"
        assert "updated_at" not in snapshots[0][1]


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_parent_index_id_into_every_video_row(self, MockSession) -> None:
        # /indexes returns two indexes, each with one video page. The parent index_id must land on
        # every row so the [index_id, _id] primary key stays unique table-wide.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),
                _page([{"_id": "v1"}], page=1, total_page=1),
                _page([{"_id": "v2"}], page=1, total_page=1),
            ],
        )

        rows = _rows(_source("videos"))

        assert rows == [{"_id": "v1", "index_id": "idx1"}, {"_id": "v2", "index_id": "idx2"}]
        assert [url for url, _ in snapshots] == [
            "https://api.twelvelabs.io/v1.3/indexes",
            "https://api.twelvelabs.io/v1.3/indexes/idx1/videos",
            "https://api.twelvelabs.io/v1.3/indexes/idx2/videos",
        ]
        # Child pages carry the videos sort params, and the resolve param never leaks into the query.
        assert snapshots[1][1]["sort_by"] == "created_at"
        assert snapshots[1][1]["page_limit"] == 50
        assert "index_id" not in snapshots[1][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_index(self, MockSession) -> None:
        # Bookmarked with idx1 already completed: idx1's videos must not be re-fetched.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),
                _page([{"_id": "v2"}], page=1, total_page=1),
            ],
        )

        manager = _make_manager(
            TwelveLabsResumeConfig(
                fanout_state={"completed": ["/indexes/idx1/videos"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("videos", manager=manager))

        assert rows == [{"_id": "v2", "index_id": "idx2"}]
        assert [url for url, _ in snapshots] == [
            "https://api.twelvelabs.io/v1.3/indexes",
            "https://api.twelvelabs.io/v1.3/indexes/idx2/videos",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_fanout_state_as_indexes_complete(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),
                _page([{"_id": "v1"}], page=1, total_page=1),
                _page([{"_id": "v2"}], page=1, total_page=1),
            ],
        )

        manager = _make_manager()
        _rows(_source("videos", manager=manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert all(isinstance(state, TwelveLabsResumeConfig) and state.fanout_state is not None for state in saved)
        final = saved[-1].fanout_state
        assert final == {
            "completed": ["/indexes/idx1/videos", "/indexes/idx2/videos"],
            "current": None,
            "child_state": None,
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_old_shape_resume_state_restarts_fanout(self, MockSession) -> None:
        # A pre-migration bookmark (index_id) can't seed the framework fan-out — the sync starts that
        # part fresh and merge dedupes the re-pulled rows on the [index_id, _id] key.
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"_id": "idx1"}, {"_id": "idx2"}], page=1, total_page=1),
                _page([{"_id": "v1"}], page=1, total_page=1),
                _page([{"_id": "v2"}], page=1, total_page=1),
            ],
        )

        manager = _make_manager(TwelveLabsResumeConfig(next_page=1, index_id="idx2"))
        rows = _rows(_source("videos", manager=manager))

        assert [r["index_id"] for r in rows] == ["idx1", "idx2"]

    def test_old_shape_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved before the
        # migration must still construct.
        state = TwelveLabsResumeConfig(**cast("dict[str, Any]", {"next_page": 2, "index_id": "idx2"}))
        assert state.next_page == 2
        assert state.index_id == "idx2"
        assert state.fanout_state is None


class TestTwelveLabsSourceResponse:
    @parameterized.expand([("indexes", ["_id"]), ("tasks", ["_id"]), ("videos", ["index_id", "_id"])])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys(self, endpoint: str, expected_keys: list[str], MockSession) -> None:
        response = _source(endpoint)
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]


class TestNonRetryableCredentialErrors:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unauthorized_raises_matchable_httperror(self, MockSession) -> None:
        # get_non_retryable_errors matches the base-host 401 text, so the raised HTTPError message
        # must carry that stable prefix (not just the per-request path).
        session = MockSession.return_value
        resp = Response()
        resp.status_code = 401
        resp.reason = "Unauthorized"
        resp.url = "https://api.twelvelabs.io/v1.3/indexes"
        resp._content = b"{}"
        _wire(session, [resp])

        with pytest.raises(Exception, match="401 Client Error: Unauthorized for url: https://api.twelvelabs.io"):
            _rows(_source("indexes"))
