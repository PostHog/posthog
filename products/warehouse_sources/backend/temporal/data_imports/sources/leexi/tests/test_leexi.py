import json
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.leexi import (
    LeexiResumeConfig,
    _make_session,
    _to_leexi_timestamp,
    leexi_source,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.settings import (
    ENDPOINTS,
    LEEXI_ENDPOINTS,
    PAGE_SIZE,
)

# The source builds its own capture-disabled session and hands it to RESTClient via the client config.
CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.leexi.leexi.make_tracked_session"
)


def _page(items: list[dict[str, Any]], count: int | None = None) -> Response:
    body = {"data": items, "pagination": {"page": 1, "items": len(items), "count": count or len(items)}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: Optional[LeexiResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, routes: list[tuple[str, Response]]) -> list[str]:
    """Wire a mock session that dispatches each request to the first still-unconsumed route whose
    substring appears in the fully-prepared URL. Returns the list of URLs sent, in order."""
    session.headers = {}
    sent_urls: list[str] = []
    remaining = list(routes)

    def _prepare(request: Any) -> Any:
        return request.prepare()

    def _send(prepared: Any, **kwargs: Any) -> Response:
        sent_urls.append(prepared.url)
        for i, (substr, response) in enumerate(remaining):
            if substr in prepared.url:
                remaining.pop(i)
                return response
        raise AssertionError(f"no route for {prepared.url}")

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return sent_urls


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Any:
    return leexi_source(
        "key-id",
        "key-secret",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


def _full_page(prefix: str = "u") -> Response:
    return _page([{"uuid": f"{prefix}{i}", "created_at": "2026-01-01T00:00:00.000Z"} for i in range(PAGE_SIZE)])


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_fetches_next_page_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("page=1", _full_page()), ("page=2", _page([{"uuid": "last"}]))])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert len(urls) == 2
        query = _query(urls[0])
        assert query["page"] == ["1"]
        assert query["items"] == [str(PAGE_SIZE)]
        # Checkpoint saved after the first (full) page; the terminal short page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == LeexiResumeConfig(paginator_state={"page": 2})

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_stops_without_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/users", _page([{"uuid": "1"}]))])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [r["uuid"] for r in rows] == ["1"]
        assert len(urls) == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("page=7", _page([{"uuid": "9"}]))])

        manager = _make_manager(LeexiResumeConfig(paginator_state={"page": 7}))
        rows = _rows(_source("users", manager))

        assert [r["uuid"] for r in rows] == ["9"]
        assert _query(urls[0])["page"] == ["7"]


class TestCallsIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_filters_and_orders_on_cursor_field(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/calls", _page([{"uuid": "c1"}]))])

        manager = _make_manager()
        _rows(
            _source(
                "calls",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        query = _query(urls[0])
        assert query["date_filter"] == ["updated_at"]
        assert query["from"] == ["2026-01-15T12:30:45.000Z"]
        assert query["order"] == ["updated_at asc"]

    @pytest.mark.parametrize("cursor_field", ["created_at", "performed_at"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_honors_user_chosen_cursor_field(self, MockSession, cursor_field) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/calls", _page([]))])

        manager = _make_manager()
        _rows(_source("calls", manager, should_use_incremental_field=True, incremental_field=cursor_field))

        query = _query(urls[0])
        assert query["date_filter"] == [cursor_field]
        assert query["order"] == [f"{cursor_field} asc"]

    def test_incremental_rejects_unsupported_cursor_field(self) -> None:
        with pytest.raises(ValueError, match="start_time"):
            _source("calls", _make_manager(), should_use_incremental_field=True, incremental_field="start_time")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_orders_by_created_at_without_date_filter(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/calls", _page([{"uuid": "c1"}]))])

        manager = _make_manager()
        _rows(_source("calls", manager))

        query = _query(urls[0])
        assert query["order"] == ["created_at asc"]
        assert query["with_simple_transcript"] == ["true"]
        assert "date_filter" not in query
        assert "from" not in query

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC), "2026-01-15T12:30:45.000Z"),
            (datetime(2026, 1, 15, 12, 30, 45), "2026-01-15T12:30:45.000Z"),
            ("2026-01-15T12:30:45.123Z", "2026-01-15T12:30:45.000Z"),
            ("2026-01-15", "2026-01-15T00:00:00.000Z"),
        ],
    )
    def test_to_leexi_timestamp_formats(self, value, expected) -> None:
        assert _to_leexi_timestamp(value) == expected


class TestCallNotesFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_one_request_per_call_and_injects_call_uuid(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(
            session,
            [
                ("/calls", _page([{"uuid": "C1"}, {"uuid": "C2"}])),
                ("call_uuid=C1", _page([{"uuid": "n1"}])),
                ("call_uuid=C2", _page([{"uuid": "n2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("call_notes", manager))

        assert [(r["uuid"], r["call_uuid"]) for r in rows] == [("n1", "C1"), ("n2", "C2")]
        # The parent listing must not pay for transcripts it never surfaces.
        assert "with_simple_transcript" not in urls[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_calls_yields_no_notes(self, MockSession) -> None:
        session = MockSession.return_value
        urls = _wire(session, [("/calls", _page([]))])

        manager = _make_manager()
        assert _rows(_source("call_notes", manager)) == []
        assert len(urls) == 1


class TestSourceResponseMetadata:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint) -> None:
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        if endpoint == "call_notes":
            assert response.primary_keys == ["call_uuid", "uuid"]
        else:
            assert response.primary_keys == ["uuid"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [LEEXI_ENDPOINTS[endpoint].partition_key]
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("config", list(LEEXI_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config) -> None:
        assert config.partition_key == "created_at"


class TestSampleCaptureDisabled:
    """Leexi call responses carry `simple_transcript`, notes, and free-form customer text; both the
    sync and probe sessions must disable HTTP sample capture so those bodies never land in the shared
    sample store outside the warehouse table's access controls."""

    def test_make_session_disables_capture_and_redacts_secret(self) -> None:
        adapters = list(_make_session("key-secret").adapters.values())
        assert adapters
        assert all(adapter._capture is False for adapter in adapters)
        assert all("key-secret" in adapter._redact_values for adapter in adapters)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_session_created_with_capture_disabled(self, MockSession) -> None:
        _wire(MockSession.return_value, [("/users", _page([]))])
        _rows(_source("users", _make_manager()))
        assert MockSession.call_args.kwargs["capture"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_probe_session_created_with_capture_disabled(self, MockSession) -> None:
        probe_endpoint("key-id", "key-secret", "/calls")
        assert MockSession.call_args.kwargs["capture"] is False
