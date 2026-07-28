import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.settings import (
    ENDPOINTS,
    STREAMELEMENTS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.streamelements import (
    StreamElementsResumeConfig,
    _to_epoch_ms,
    get_channel_id,
    streamelements_source,
    validate_credentials,
)

# Every StreamElements request — the pipeline client session, channel resolution and the
# credential probe — runs on a session built by the shared _tracked_session factory, which
# calls make_tracked_session in the streamelements module. Patch that one symbol.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.streamelements.make_tracked_session"

CHANNEL_ID = "5b2e2007760aeb7729487dab"


def _response(payload: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: StreamElementsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    Channel resolution goes through ``.get``; the pipeline goes through ``.prepare_request``/``.send``.
    """
    session.headers = {}
    session.get.return_value = _response({"_id": CHANNEL_ID})
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return streamelements_source("jwt", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _tip(i: int, created_at: str = "2024-01-01T00:00:00.000Z") -> dict[str, Any]:
    return {"_id": f"tip{i}", "createdAt": created_at, "donation": {"amount": i}}


def _activity(i: int, created_at: str) -> dict[str, Any]:
    return {"_id": f"act{i}", "type": "follow", "createdAt": created_at}


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC), 1567785250202),
            (datetime(2019, 9, 6, 15, 54, 10, 202000), 1567785250202),
            (date(2019, 9, 6), 1567728000000),
            (1567785250202, 1567785250202),
            ("1567785250202", 1567785250202),
            ("2019-09-06T15:54:10.202Z", 1567785250202),
            ("nope", None),
        ],
    )
    def test_to_epoch_ms(self, value: Any, expected: Any) -> None:
        assert _to_epoch_ms(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        mock_session.return_value.get.return_value = _response({"_id": CHANNEL_ID}, status_code=status_code)
        valid, _ = validate_credentials("jwt")
        assert valid is expected_valid

    @mock.patch(SESSION_PATCH)
    def test_request_exception_returns_error(self, mock_session: mock.MagicMock) -> None:
        import requests

        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        valid, message = validate_credentials("jwt")
        assert valid is False
        assert message == "boom"


class TestCaptureDisabled:
    """StreamElements payloads carry donor emails and free-text tip/chat messages the name-based
    scrubbers can't recognise, so every session must be built with capture=False. These lock that
    in for the pipeline client session and both direct probe paths."""

    @mock.patch(SESSION_PATCH)
    def test_pipeline_session_disables_capture(self, mock_session: mock.MagicMock) -> None:
        session = mock_session.return_value
        _wire(session, [_response({"docs": [_tip(1)], "total": 1})])
        _rows(_source("tips", _make_manager()))

        assert mock_session.call_args_list  # sanity: the pipeline built at least one session
        for call in mock_session.call_args_list:
            assert call.kwargs.get("capture") is False
            assert call.kwargs.get("redact_values") == ("jwt",)

    @mock.patch(SESSION_PATCH)
    def test_get_channel_id_disables_capture(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"_id": CHANNEL_ID})
        get_channel_id("jwt")
        mock_session.assert_called_once_with(redact_values=("jwt",), capture=False)

    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_disables_capture(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"_id": CHANNEL_ID})
        validate_credentials("jwt")
        mock_session.assert_called_once_with(redact_values=("jwt",), capture=False)


class TestTips:
    @mock.patch(SESSION_PATCH)
    def test_paginates_offsets_until_total(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"docs": [_tip(i) for i in range(100)], "total": 150}),
                _response({"docs": [_tip(100 + i) for i in range(50)], "total": 150}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("tips", manager))

        assert session.send.call_count == 2
        assert len(rows) == 150
        assert snapshots[0]["url"].endswith(f"/tips/{CHANNEL_ID}")
        assert snapshots[0]["params"]["offset"] == 0
        assert snapshots[0]["params"]["limit"] == 100
        assert snapshots[0]["params"]["sort"] == "createdAt"
        assert snapshots[1]["params"]["offset"] == 100
        # The next offset is checkpointed after each yielded page; the final page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == StreamElementsResumeConfig(paginator_state={"offset": 100})

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"docs": [_tip(1)], "total": 301})])

        _rows(_source("tips", _make_manager(StreamElementsResumeConfig(paginator_state={"offset": 300}))))
        assert snapshots[0]["params"]["offset"] == 300

    @mock.patch(SESSION_PATCH)
    def test_incremental_adds_after_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"docs": [_tip(1)], "total": 1})])

        _rows(
            _source(
                "tips",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2019, 9, 6, 15, 54, 10, 202000, tzinfo=UTC),
            )
        )
        assert snapshots[0]["params"]["after"] == 1567785250202

    @mock.patch(SESSION_PATCH)
    def test_full_refresh_omits_after_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"docs": [_tip(1)], "total": 1})])

        _rows(_source("tips", _make_manager(), should_use_incremental_field=False))
        assert "after" not in snapshots[0]["params"]

    @mock.patch(SESSION_PATCH)
    def test_unexpected_body_shape_fails_loud(self, MockSession: mock.MagicMock) -> None:
        # A bare array where {"docs": [...]} is expected must raise, not silently sync 0 rows.
        session = MockSession.return_value
        _wire(session, [_response([_tip(1)])])

        with pytest.raises(ValueError, match="data_selector"):
            _rows(_source("tips", _make_manager()))


class TestActivities:
    @mock.patch(SESSION_PATCH)
    def test_walks_before_bound_down_until_short_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        # Newest-first pages; the oldest event of page one is at 2024-01-02T00:00:00Z.
        page_one = [_activity(i, "2024-01-03T00:00:00.000Z") for i in range(99)] + [
            _activity(99, "2024-01-02T00:00:00.000Z")
        ]
        page_two = [_activity(100, "2024-01-01T00:00:00.000Z")]
        snapshots = _wire(session, [_response(page_one), _response(page_two)])

        manager = _make_manager()
        rows = _rows(_source("activities", manager))

        assert session.send.call_count == 2
        assert len(rows) == 101
        assert snapshots[0]["url"].endswith(f"/activities/{CHANNEL_ID}")
        assert snapshots[0]["params"]["limit"] == 100
        # Page two's upper bound moves to just past page one's oldest event so events sharing
        # that millisecond aren't skipped.
        oldest_ms = 1704153600000  # 2024-01-02T00:00:00Z
        assert snapshots[1]["params"]["before"] == oldest_ms + 1
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == StreamElementsResumeConfig(
            paginator_state={"before": oldest_ms + 1}
        )

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_before_bound(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([_activity(1, "2024-01-01T00:00:00.000Z")])])

        _rows(
            _source("activities", _make_manager(StreamElementsResumeConfig(paginator_state={"before": 1704153600000})))
        )
        assert snapshots[0]["params"]["before"] == 1704153600000

    @mock.patch(SESSION_PATCH)
    def test_incremental_keeps_after_filter_on_every_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        page_one = [_activity(i, "2024-01-02T00:00:00.000Z") for i in range(100)]
        page_two = [_activity(100, "2024-01-01T00:00:00.000Z")]
        snapshots = _wire(session, [_response(page_one), _response(page_two)])

        _rows(
            _source(
                "activities",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2023-12-01T00:00:00.000Z",
            )
        )
        watermark_ms = 1701388800000  # 2023-12-01T00:00:00Z
        assert snapshots[0]["params"]["after"] == watermark_ms
        assert snapshots[1]["params"]["after"] == watermark_ms

    @mock.patch(SESSION_PATCH)
    def test_full_page_of_identical_timestamps_still_progresses(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        same_ms = "2024-01-02T00:00:00.000Z"
        snapshots = _wire(
            session,
            [
                _response([_activity(i, same_ms) for i in range(100)]),
                _response([_activity(200, same_ms)]),
            ],
        )

        _rows(
            _source("activities", _make_manager(StreamElementsResumeConfig(paginator_state={"before": 1704153600001})))
        )
        # before must strictly decrease even when a whole page shares the bound's millisecond,
        # otherwise pagination loops on the same window forever.
        assert snapshots[1]["params"]["before"] < snapshots[0]["params"]["before"]


class TestSinglePageEndpoints:
    @mock.patch(SESSION_PATCH)
    def test_bot_commands_returns_bare_array(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"_id": "c1", "command": "test"}])])

        rows = _rows(_source("bot_commands", _make_manager()))

        assert session.send.call_count == 1
        assert snapshots[0]["url"].endswith(f"/bot/commands/{CHANNEL_ID}")
        assert [row["_id"] for row in rows] == ["c1"]

    @mock.patch(SESSION_PATCH)
    def test_channel_yields_single_row_without_channel_resolution(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"_id": CHANNEL_ID, "username": "streamer"})])

        rows = _rows(_source("channel", _make_manager()))

        # /channels/me needs no channel id in the path, so get_channel_id (which probes via .get)
        # is never invoked — the row comes straight from the pipeline .send path.
        session.get.assert_not_called()
        assert snapshots[0]["url"].endswith("/channels/me")
        assert rows == [{"_id": CHANNEL_ID, "username": "streamer"}]


class TestLeaderboards:
    @mock.patch(SESSION_PATCH)
    def test_points_leaderboard_unwraps_users_with_big_pages(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_response({"_total": 2, "users": [{"username": "a", "points": 2}, {"username": "b", "points": 1}]})],
        )

        rows = _rows(_source("points_leaderboard", _make_manager()))

        assert snapshots[0]["url"].endswith(f"/points/{CHANNEL_ID}/top")
        assert snapshots[0]["params"]["limit"] == 1000
        assert [row["username"] for row in rows] == ["a", "b"]


class TestStreamElementsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, mock_session: mock.MagicMock, endpoint: str) -> None:
        mock_session.return_value.get.return_value = _response({"_id": CHANNEL_ID})
        config = STREAMELEMENTS_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @mock.patch(SESSION_PATCH)
    def test_activities_use_desc_sort_mode(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"_id": CHANNEL_ID})
        assert _source("activities", _make_manager()).sort_mode == "desc"

    @mock.patch(SESSION_PATCH)
    def test_tips_use_asc_sort_mode(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response({"_id": CHANNEL_ID})
        assert _source("tips", _make_manager()).sort_mode == "asc"

    @pytest.mark.parametrize("config", list(STREAMELEMENTS_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        if config.partition_key:
            assert config.partition_key == "createdAt"
