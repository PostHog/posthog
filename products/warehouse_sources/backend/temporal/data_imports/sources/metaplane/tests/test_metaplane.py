import re
import json
from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.metaplane import (
    EVALUATION_PAGE_LIMIT,
    METAPLANE_BASE_URL,
    MetaplaneResumeConfig,
    _format_datetime,
    get_rows,
    metaplane_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.settings import METAPLANE_ENDPOINTS

METAPLANE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.metaplane"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = f"{METAPLANE_BASE_URL}/test"
    return resp


class _FakeAPI:
    """Routes tracked-session requests to canned Metaplane responses, recording every call."""

    def __init__(
        self,
        connections: list[dict[str, Any]] | None = None,
        monitors_by_connection: dict[str, Any] | None = None,
        evaluation_pages_by_monitor: dict[str, list[Any]] | None = None,
        sync_status_by_connection: dict[str, Any] | None = None,
    ) -> None:
        self.connections = connections or []
        self.monitors_by_connection = monitors_by_connection or {}
        self.evaluation_pages_by_monitor = {k: list(v) for k, v in (evaluation_pages_by_monitor or {}).items()}
        self.sync_status_by_connection = sync_status_by_connection or {}
        self.calls: list[tuple[str, str, Any]] = []

    def request(self, method: str, url: str, headers: Any = None, json: Any = None, timeout: Any = None) -> Response:
        self.calls.append((method, url, json))

        if url == f"{METAPLANE_BASE_URL}/connections":
            return _response(self.connections)

        match = re.fullmatch(rf"{METAPLANE_BASE_URL}/monitors/connection/([^/?]+)\?includeDisabled=true", url)
        if match:
            monitors = self.monitors_by_connection.get(match.group(1))
            if monitors is None:
                return _response({}, status_code=404)
            return _response({"data": monitors})

        match = re.fullmatch(rf"{METAPLANE_BASE_URL}/monitors/evaluation-history/([^/?]+)", url)
        if match:
            pages = self.evaluation_pages_by_monitor.get(match.group(1))
            if pages is None:
                return _response({}, status_code=404)
            return _response(pages.pop(0) if pages else [])

        match = re.fullmatch(rf"{METAPLANE_BASE_URL}/connections/([^/?]+)/sync/status", url)
        if match:
            status = self.sync_status_by_connection.get(match.group(1))
            if status is None:
                return _response({}, status_code=404)
            return _response(status)

        raise AssertionError(f"Unexpected request: {method} {url}")

    def evaluation_bodies(self, monitor_id: str) -> list[Any]:
        return [
            body
            for method, url, body in self.calls
            if method == "POST" and url == f"{METAPLANE_BASE_URL}/monitors/evaluation-history/{monitor_id}"
        ]


def _make_manager(resume: MetaplaneResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive(
    api: _FakeAPI,
    endpoint: str,
    manager: MagicMock | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[list[dict[str, Any]]]:
    with patch(f"{METAPLANE_MODULE}.make_tracked_session", return_value=api):
        return list(
            get_rows(
                api_key="key",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager if manager is not None else _make_manager(),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )


def _evaluation(created_at: str, **extra: Any) -> dict[str, Any]:
    return {"createdAt": created_at, "result": 1.0, "passed": True, **extra}


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (
                "microseconds_truncated_to_millis",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with patch(f"{METAPLANE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response([], status_code=status_code)
            assert validate_credentials("key") is expected

    def test_network_error_returns_invalid(self) -> None:
        with patch(f"{METAPLANE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False

    def test_raw_api_key_in_authorization_header(self) -> None:
        # Metaplane expects the bare key, not a Bearer-prefixed one — a prefix breaks auth.
        with patch(f"{METAPLANE_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response([], status_code=200)
            validate_credentials("mp-key")
            headers = mock_session.return_value.get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "mp-key"


class TestConnectionsEndpoint:
    def test_yields_connection_rows(self) -> None:
        api = _FakeAPI(connections=[{"id": "c1"}, {"id": "c2"}])
        assert _drive(api, "connections") == [[{"id": "c1"}, {"id": "c2"}]]

    def test_empty_account_yields_nothing(self) -> None:
        assert _drive(_FakeAPI(connections=[]), "connections") == []


class TestMonitorsEndpoint:
    def test_fans_out_over_connections(self) -> None:
        api = _FakeAPI(
            connections=[{"id": "c1"}, {"id": "c2"}],
            monitors_by_connection={"c1": [{"id": "m1"}], "c2": [{"id": "m2"}, {"id": "m3"}]},
        )
        batches = _drive(api, "monitors")
        assert [row["id"] for batch in batches for row in batch] == ["m1", "m2", "m3"]

    def test_deleted_connection_is_skipped(self) -> None:
        # c1 404s (deleted between enumeration and fetch); the sync must continue with c2.
        api = _FakeAPI(connections=[{"id": "c1"}, {"id": "c2"}], monitors_by_connection={"c2": [{"id": "m2"}]})
        batches = _drive(api, "monitors")
        assert [row["id"] for batch in batches for row in batch] == ["m2"]


class TestConnectionSyncStatusesEndpoint:
    def test_rows_keyed_on_connection(self) -> None:
        # The API response carries connectionId itself, but a missing one must still be
        # filled in — it's the table's primary key.
        api = _FakeAPI(
            connections=[{"id": "c1"}, {"id": "c2"}],
            sync_status_by_connection={
                "c1": {"status": "SUCCEEDED", "connectionId": "c1"},
                "c2": {"status": "ERRORED"},
            },
        )
        batches = _drive(api, "connection_sync_statuses")
        assert [(row["connectionId"], row["status"]) for batch in batches for row in batch] == [
            ("c1", "SUCCEEDED"),
            ("c2", "ERRORED"),
        ]

    def test_connection_without_status_is_skipped(self) -> None:
        api = _FakeAPI(
            connections=[{"id": "c1"}, {"id": "c2"}],
            sync_status_by_connection={"c2": {"status": "SUCCEEDED", "connectionId": "c2"}},
        )
        batches = _drive(api, "connection_sync_statuses")
        assert [row["connectionId"] for batch in batches for row in batch] == ["c2"]


class TestEvaluationHistory:
    def _single_monitor_api(self, pages: list[Any]) -> _FakeAPI:
        return _FakeAPI(
            connections=[{"id": "c1"}],
            monitors_by_connection={"c1": [{"id": "m1"}]},
            evaluation_pages_by_monitor={"m1": pages},
        )

    def test_rows_carry_injected_monitor_id(self) -> None:
        api = self._single_monitor_api([[_evaluation("2026-01-01T00:00:00.000Z")]])
        batches = _drive(api, "monitor_evaluations")
        assert batches == [
            [{"createdAt": "2026-01-01T00:00:00.000Z", "result": 1.0, "passed": True, "monitorId": "m1"}]
        ]

    def test_full_page_requests_next_page_from_last_created_at(self) -> None:
        full_page = [_evaluation(f"2026-01-01T00:00:{i:02d}.000Z") for i in range(EVALUATION_PAGE_LIMIT)]
        api = self._single_monitor_api([full_page, [_evaluation("2026-01-01T01:00:00.000Z")]])
        manager = _make_manager()

        _drive(api, "monitor_evaluations", manager)

        bodies = api.evaluation_bodies("m1")
        assert "createdAt" not in bodies[0]
        assert bodies[0]["sortOrder"] == "ASC"
        assert bodies[1]["createdAt"] == full_page[-1]["createdAt"]
        # State is saved after yielding the full page so a crash re-yields it (merge dedupes).
        manager.save_state.assert_called_once_with(
            MetaplaneResumeConfig(monitor_id="m1", cursor=full_page[-1]["createdAt"])
        )

    def test_short_page_terminates_pagination(self) -> None:
        api = self._single_monitor_api([[_evaluation("2026-01-01T00:00:00.000Z")]])
        _drive(api, "monitor_evaluations")
        assert len(api.evaluation_bodies("m1")) == 1

    def test_non_advancing_cursor_stops_pagination(self) -> None:
        # A full page of identical timestamps would otherwise re-request the same page forever.
        same_ts_page = [_evaluation("2026-01-01T00:00:00.000Z") for _ in range(EVALUATION_PAGE_LIMIT)]
        api = self._single_monitor_api([same_ts_page, same_ts_page])
        manager = _make_manager(MetaplaneResumeConfig(monitor_id="m1", cursor="2026-01-01T00:00:00.000Z"))

        batches = _drive(api, "monitor_evaluations", manager)

        assert len(api.evaluation_bodies("m1")) == 1
        assert len(batches) == 1

    def test_incremental_watermark_seeds_initial_cursor(self) -> None:
        api = self._single_monitor_api([[_evaluation("2026-03-05T00:00:00.000Z")]])
        _drive(
            api,
            "monitor_evaluations",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert api.evaluation_bodies("m1")[0]["createdAt"] == "2026-03-04T02:58:14.000Z"

    def test_full_refresh_omits_cursor(self) -> None:
        api = self._single_monitor_api([[_evaluation("2026-03-05T00:00:00.000Z")]])
        _drive(api, "monitor_evaluations")
        assert "createdAt" not in api.evaluation_bodies("m1")[0]

    def test_bookmark_advances_to_next_monitor(self) -> None:
        api = _FakeAPI(
            connections=[{"id": "c1"}],
            monitors_by_connection={"c1": [{"id": "m1"}, {"id": "m2"}]},
            evaluation_pages_by_monitor={
                "m1": [[_evaluation("2026-01-01T00:00:00.000Z")]],
                "m2": [[_evaluation("2026-01-02T00:00:00.000Z")]],
            },
        )
        manager = _make_manager()

        batches = _drive(api, "monitor_evaluations", manager)

        assert [row["monitorId"] for batch in batches for row in batch] == ["m1", "m2"]
        # After finishing m1 the bookmark moves to m2 so a crash between monitors resumes there.
        manager.save_state.assert_called_once_with(MetaplaneResumeConfig(monitor_id="m2", cursor=None))

    def test_resume_skips_completed_monitors_and_uses_saved_cursor(self) -> None:
        api = _FakeAPI(
            connections=[{"id": "c1"}],
            monitors_by_connection={"c1": [{"id": "m1"}, {"id": "m2"}]},
            evaluation_pages_by_monitor={
                "m1": [[_evaluation("2026-01-01T00:00:00.000Z")]],
                "m2": [[_evaluation("2026-01-02T00:00:00.000Z")]],
            },
        )
        manager = _make_manager(MetaplaneResumeConfig(monitor_id="m2", cursor="2026-01-01T12:00:00.000Z"))

        batches = _drive(api, "monitor_evaluations", manager)

        assert api.evaluation_bodies("m1") == []
        assert api.evaluation_bodies("m2")[0]["createdAt"] == "2026-01-01T12:00:00.000Z"
        assert [row["monitorId"] for batch in batches for row in batch] == ["m2"]

    def test_resume_with_deleted_bookmark_monitor_starts_over(self) -> None:
        api = self._single_monitor_api([[_evaluation("2026-01-01T00:00:00.000Z")]])
        manager = _make_manager(MetaplaneResumeConfig(monitor_id="gone", cursor="2026-01-01T12:00:00.000Z"))

        batches = _drive(api, "monitor_evaluations", manager)

        assert [row["monitorId"] for batch in batches for row in batch] == ["m1"]
        assert "createdAt" not in api.evaluation_bodies("m1")[0]

    def test_monitor_without_history_is_skipped(self) -> None:
        # A monitor that was deleted (or never modeled) 404s; the sync continues with the rest.
        api = _FakeAPI(
            connections=[{"id": "c1"}],
            monitors_by_connection={"c1": [{"id": "m1"}, {"id": "m2"}]},
            evaluation_pages_by_monitor={"m2": [[_evaluation("2026-01-02T00:00:00.000Z")]]},
        )
        batches = _drive(api, "monitor_evaluations")
        assert [row["monitorId"] for batch in batches for row in batch] == ["m2"]


class TestMetaplaneSourceResponse:
    @parameterized.expand([(name,) for name in sorted(METAPLANE_ENDPOINTS)])
    def test_source_response_matches_endpoint_settings(self, endpoint: str) -> None:
        response = metaplane_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_make_manager(),
        )
        config = METAPLANE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Only the monitor fan-out defers the watermark to job end.
        assert response.sort_mode == ("desc" if endpoint == "monitor_evaluations" else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
