import copy
import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security import orca_security
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.orca_security import (
    OrcaResumeConfig,
    _build_query_body,
    _format_datetime,
    _headers,
    _host,
    _normalize_item,
    orca_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import (
    ORCA_ENDPOINTS,
    PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(
    items: list[dict[str, Any]] | None, *, next_token: int | None = None, drop_data: bool = False
) -> Response:
    body: dict[str, Any] = {"next_page_token": next_token}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _page(ids: list[str], *, next_token: int | None = None) -> Response:
    return _response(
        [{"id": i, "type": "Alert", "data": {"AlertId": {"value": i}}} for i in ids], next_token=next_token
    )


def _make_manager(resume_state: OrcaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's JSON body AT SEND TIME.

    ``request.json`` is one dict mutated in place across pages (the paginator rewrites
    ``start_at_index``), so snapshot a deep copy when each request is prepared.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(copy.deepcopy(request.json) if request.json is not None else {})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestHost:
    @parameterized.expand(
        [
            ("global", "https://api.orcasecurity.io/api"),
            ("us", "https://app.us.orcasecurity.io/api"),
            ("eu", "https://app.eu.orcasecurity.io/api"),
            ("", "https://api.orcasecurity.io/api"),
            ("unknown", "https://api.orcasecurity.io/api"),
        ]
    )
    def test_host_mapping(self, region: str, expected: str) -> None:
        assert _host(region) == expected


class TestHeaders:
    def test_token_header(self) -> None:
        headers = _headers("abc123")
        assert headers["Authorization"] == "Token abc123"
        assert headers["Content-Type"] == "application/json"


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestBuildQueryBody:
    def test_full_refresh_has_no_filter_or_order(self) -> None:
        body = _build_query_body(ORCA_ENDPOINTS["assets"], incremental_field=None, formatted_last_value=None)
        assert body["query"] == {"models": ["Inventory"], "type": "object_set"}
        assert body["limit"] == PAGE_SIZE
        assert "with" not in body["query"]
        assert "order_by[]" not in body

    def test_incremental_stream_always_sorts(self) -> None:
        body = _build_query_body(ORCA_ENDPOINTS["alerts"], incremental_field=None, formatted_last_value=None)
        # Even on first sync (no watermark), the incremental stream requests ascending order so the
        # pipeline watermark advances correctly.
        assert body["order_by[]"] == ["CreatedAt"]
        assert "with" not in body["query"]

    def test_incremental_filter_applied(self) -> None:
        body = _build_query_body(
            ORCA_ENDPOINTS["alerts"],
            incremental_field="CreatedAt",
            formatted_last_value="2026-01-01T00:00:00+00:00",
        )
        with_clause = body["query"]["with"]
        assert with_clause["operator"] == "and"
        value = with_clause["values"][0]
        assert value["key"] == "CreatedAt"
        assert value["operator"] == "date_gte"
        assert value["values"] == ["2026-01-01T00:00:00+00:00"]

    def test_incremental_field_override(self) -> None:
        body = _build_query_body(
            ORCA_ENDPOINTS["alerts"],
            incremental_field="LastSeen",
            formatted_last_value="2026-01-01T00:00:00+00:00",
        )
        assert body["query"]["with"]["values"][0]["key"] == "LastSeen"


class TestNormalizeItem:
    def test_unwraps_value_fields(self) -> None:
        item = {
            "id": "acc_1_alert_1",
            "type": "Alert",
            "data": {
                "AlertId": {"value": "alert_1"},
                "Category": {"value": "IAM misconfigurations"},
                "Labels": {"value": ["a", "b"]},
            },
        }
        assert _normalize_item(item) == {
            "id": "acc_1_alert_1",
            "type": "Alert",
            "AlertId": "alert_1",
            "Category": "IAM misconfigurations",
            "Labels": ["a", "b"],
        }

    def test_keeps_unwrapped_field(self) -> None:
        assert _normalize_item({"id": "x", "data": {"Raw": {"nested": 1}}})["Raw"] == {"nested": 1}

    def test_missing_data(self) -> None:
        assert _normalize_item({"id": "x", "type": "Alert"}) == {"id": "x", "type": "Alert"}


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(
            session,
            [_page([str(n) for n in range(PAGE_SIZE)], next_token=PAGE_SIZE), _page(["last"])],
        )

        manager = _make_manager()
        rows = _rows(orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1]["id"] == "last"
        # Rows are normalized on the way out.
        assert rows[-1]["AlertId"] == "last"
        # start_at_index progresses 0 -> PAGE_SIZE (the continuation token).
        assert bodies[0]["start_at_index"] == 0
        assert bodies[1]["start_at_index"] == PAGE_SIZE
        # Checkpoint saved once after the first full page; the short page ends the stream.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OrcaResumeConfig(start_at_index=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_next_page_token_overrides_offset(self, MockSession) -> None:
        session = MockSession.return_value
        # A full page carrying a token whose value is NOT offset+len must be used verbatim.
        bodies = _wire(session, [_page([str(n) for n in range(PAGE_SIZE)], next_token=500), _page(["x"])])

        _rows(orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert bodies[1]["start_at_index"] == 500

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_by_page_length_without_token(self, MockSession) -> None:
        session = MockSession.return_value
        # A full page with no token advances by the number of rows returned.
        bodies = _wire(session, [_page([str(n) for n in range(PAGE_SIZE)]), _page(["x"])])

        _rows(orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert bodies[1]["start_at_index"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page(["a", "b"])])

        manager = _make_manager()
        rows = _rows(orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_page(["r"])])

        manager = _make_manager(OrcaResumeConfig(start_at_index=PAGE_SIZE))
        _rows(orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=manager))

        # First fetch continues from the saved offset rather than 0.
        assert bodies[0]["start_at_index"] == PAGE_SIZE


class TestIncrementalBody:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_filter_in_body_only_when_incremental_used(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_page(["a"])])

        _rows(
            orca_source(
                "tok",
                "us",
                "alerts",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        assert bodies[0]["query"]["with"]["values"][0]["values"] == ["2026-01-01T00:00:00+00:00"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_when_not_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_page(["a"])])

        _rows(orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert "with" not in bodies[0]["query"]
        assert bodies[0]["order_by[]"] == ["CreatedAt"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
        ]
    )
    def test_status_mapping(self, status: int, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.ok = status == 200
        session = mock.MagicMock()
        session.post.return_value = response
        with mock.patch.object(orca_security, "make_tracked_session", return_value=session):
            ok, _err = validate_credentials("tok", "us")
        assert ok is expected

    def test_network_error_is_failure(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = Exception("boom")
        with mock.patch.object(orca_security, "make_tracked_session", return_value=session):
            ok, err = validate_credentials("tok", "us")
        assert ok is False
        assert err is not None


class TestOrcaSource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_alerts_is_partitioned_and_ascending(self, MockSession) -> None:
        response = orca_source("tok", "us", "alerts", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == "alerts"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["CreatedAt"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_stream_has_no_partition(self, MockSession) -> None:
        response = orca_source("tok", "us", "assets", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
