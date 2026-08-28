import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.plivo import (
    PlivoResumeConfig,
    _build_windows,
    get_rows,
    plivo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.settings import ENDPOINTS, PAGE_SIZE

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the plivo module.
PLIVO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.plivo.plivo.make_tracked_session"
)

FROZEN_NOW = "2026-07-21 12:00:00"
MESSAGE_URL = "https://api.plivo.com/v1/Account/MA123/Message/"


def _make_manager(resume_state: PlivoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(objects: list[dict[str, Any]], total_count: int) -> dict[str, Any]:
    return {"meta": {"limit": PAGE_SIZE, "total_count": total_count}, "objects": objects}


def _wire(session: mock.MagicMock, respond: Callable[[str, dict[str, Any]], dict[str, Any]]) -> list[dict[str, Any]]:
    """Wire a mock session that routes each request through `respond(url, params)`.

    Params are snapshotted at prepare time — the paginator mutates the params dict in place
    across pages, so inspecting it after the run would only show the final state.
    """
    session.headers = {}
    calls: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snap = {"url": request.url, "params": dict(request.params or {})}
        calls.append(snap)
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.snap = snap
        return prepared

    def _send(prepared: Any, **kwargs: Any) -> Response:
        resp = Response()
        resp.status_code = 200
        resp.url = prepared.url
        resp._content = json.dumps(respond(prepared.snap["url"], prepared.snap["params"])).encode()
        return resp

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return calls


def _run(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> list[list[dict[str, Any]]]:
    return list(
        get_rows(
            auth_id="MA123",
            auth_token="token",
            endpoint=endpoint,
            resumable_source_manager=manager,
            **kwargs,
        )
    )


class TestBuildWindows:
    @pytest.mark.parametrize(
        "start_days_ago, expected_boundaries",
        [
            # 90-day span chunks into three contiguous 30-day windows.
            (90, ["2026-04-22 12:00", "2026-05-22 12:00", "2026-06-21 12:00", "2026-07-21 12:00"]),
            # A span under 30 days is a single window.
            (10, ["2026-07-11 12:00", "2026-07-21 12:00"]),
            # A start at/after the end yields no windows (e.g. a future-dated cursor).
            (0, ["2026-07-21 12:00"]),
            (-5, []),
        ],
    )
    def test_windows_are_contiguous_and_capped_at_30_days(self, start_days_ago, expected_boundaries):
        end = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
        windows = _build_windows(end - timedelta(days=start_days_ago), end)

        if len(expected_boundaries) < 2:
            assert windows == []
            return

        boundaries = [windows[0][0], *(w[1] for w in windows)]
        assert [b.strftime("%Y-%m-%d %H:%M") for b in boundaries] == expected_boundaries
        assert all(we - ws <= timedelta(days=30) for ws, we in windows)


@freeze_time(FROZEN_NOW)
class TestWindowedEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_walks_retention_in_30_day_windows(self, MockSession: mock.MagicMock) -> None:
        calls = _wire(MockSession.return_value, lambda url, params: _page([], 0))

        _run("messages", _make_manager())

        # 90 days of retention → three contiguous 30-day windows, each filtered server-side.
        windows = [(c["params"]["message_time__gt"], c["params"]["message_time__lte"]) for c in calls]
        assert windows == [
            ("2026-04-22 12:00:00", "2026-05-22 12:00:00"),
            ("2026-05-22 12:00:00", "2026-06-21 12:00:00"),
            ("2026-06-21 12:00:00", "2026-07-21 12:00:00"),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_starts_at_cursor_and_filters_server_side(self, MockSession: mock.MagicMock) -> None:
        calls = _wire(
            MockSession.return_value,
            lambda url, params: _page([{"message_uuid": "m1", "message_time": "2026-07-15 09:30:00+00:00"}], 1),
        )

        batches = _run(
            "messages",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
            incremental_field="message_time",
        )

        assert len(calls) == 1
        assert calls[0]["url"] == MESSAGE_URL
        assert calls[0]["params"]["message_time__gt"] == "2026-07-11 12:00:00"
        assert calls[0]["params"]["message_time__lte"] == "2026-07-21 12:00:00"
        assert calls[0]["params"]["limit"] == PAGE_SIZE
        assert calls[0]["params"]["offset"] == 0

        rows = [row for batch in batches for row in batch]
        assert [r["message_uuid"] for r in rows] == ["m1"]
        # Timestamp strings are parsed so the incremental watermark compares datetimes.
        assert rows[0]["message_time"] == datetime(2026, 7, 15, 9, 30, 0, tzinfo=UTC)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_future_cursor_makes_no_requests(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, lambda url, params: _page([], 0))

        batches = _run(
            "messages",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 8, 1, tzinfo=UTC),
            incremental_field="message_time",
        )

        assert batches == []
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pagination_saves_offset_then_window_checkpoint(self, MockSession: mock.MagicMock) -> None:
        def respond(url: str, params: dict[str, Any]) -> dict[str, Any]:
            offset = params["offset"]
            rows = [{"message_uuid": f"m{offset + i}"} for i in range(PAGE_SIZE if offset == 0 else 5)]
            return _page(rows, total_count=PAGE_SIZE + 5)

        calls = _wire(MockSession.return_value, respond)
        manager = _make_manager()

        batches = _run(
            "messages",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
            incremental_field="message_time",
        )

        assert [params["offset"] for params in (c["params"] for c in calls)] == [0, PAGE_SIZE]
        assert sum(len(b) for b in batches) == PAGE_SIZE + 5

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        # Mid-window: checkpoint the next page offset with the window bounds pinned.
        assert saved[0].offset == PAGE_SIZE
        assert saved[0].window_start == datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC).isoformat()
        assert saved[0].window_end == datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC).isoformat()
        # Window exhausted: checkpoint points at the next window's start with a fresh offset.
        assert saved[-1].window_start == datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC).isoformat()
        assert saved[-1].offset == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_pins_saved_window_and_offset(self, MockSession: mock.MagicMock) -> None:
        calls = _wire(MockSession.return_value, lambda url, params: _page([{"message_uuid": "x"}], 1))

        window_start = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)
        window_end = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)
        manager = _make_manager(
            PlivoResumeConfig(window_start=window_start.isoformat(), window_end=window_end.isoformat(), offset=40)
        )

        _run("messages", manager)

        # First request resumes the saved window at the saved page offset...
        assert calls[0]["params"]["message_time__gt"] == "2026-06-11 12:00:00"
        assert calls[0]["params"]["message_time__lte"] == "2026-07-11 12:00:00"
        assert calls[0]["params"]["offset"] == 40
        # ...then the walk continues from the saved window's end to now, from offset 0.
        assert calls[1]["params"]["message_time__gt"] == "2026-07-11 12:00:00"
        assert calls[1]["params"]["message_time__lte"] == "2026-07-21 12:00:00"
        assert calls[1]["params"]["offset"] == 0


@freeze_time(FROZEN_NOW)
class TestNonWindowedEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_recordings_incremental_filters_without_windowing(self, MockSession: mock.MagicMock) -> None:
        calls = _wire(MockSession.return_value, lambda url, params: _page([{"recording_id": "r1", "add_time": ""}], 1))

        batches = _run(
            "recordings",
            _make_manager(),
            should_use_incremental_field=True,
            # A cursor older than the 90-day MDR/CDR retention must NOT be clamped here —
            # recordings persist until deleted.
            db_incremental_field_last_value=datetime(2025, 1, 1, tzinfo=UTC),
            incremental_field="add_time",
        )

        assert len(calls) == 1
        assert calls[0]["url"] == "https://api.plivo.com/v1/Account/MA123/Recording/"
        assert calls[0]["params"]["add_time__gt"] == "2025-01-01 00:00:00"
        assert "add_time__lte" not in calls[0]["params"]
        # An empty timestamp string stays untouched instead of failing the row.
        assert batches[0][0]["add_time"] == ""

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_applications_full_refresh_has_no_filters_and_resumes_offset(self, MockSession: mock.MagicMock) -> None:
        calls = _wire(MockSession.return_value, lambda url, params: _page([{"app_id": "a1"}], 41))

        manager = _make_manager(PlivoResumeConfig(offset=40))
        _run("applications", manager)

        assert calls[0]["url"] == "https://api.plivo.com/v1/Account/MA123/Application/"
        assert calls[0]["params"] == {"limit": PAGE_SIZE, "offset": 40}


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(PLIVO_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("MA123", "token") is expected
        assert mock_session.return_value.get.call_args.args[0] == "https://api.plivo.com/v1/Account/MA123/"


class TestPlivoSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_keys",
        [
            ("messages", ["message_uuid"], ["message_time"]),
            ("calls", ["call_uuid"], ["end_time"]),
            ("recordings", ["recording_id"], ["add_time"]),
            ("applications", ["app_id"], None),
        ],
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_keys) -> None:
        assert endpoint in ENDPOINTS
        response = plivo_source("MA123", "token", endpoint, resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        # Plivo lists return newest-first with no sort param, so the watermark must only be
        # persisted after a fully successful run.
        assert response.sort_mode == "desc"
