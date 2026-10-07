import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.settings import (
    STREAMELEMENTS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.streamelements import (
    StreamElementsResumeConfig,
    _to_epoch_ms,
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


def _source(endpoint: str, manager: mock.MagicMock, *, api_version: str = "v2", **kwargs: Any):
    return streamelements_source(
        "jwt", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, api_version=api_version, **kwargs
    )


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
        valid, _ = validate_credentials("jwt", "v2")
        assert valid is expected_valid

    @mock.patch(SESSION_PATCH)
    def test_request_exception_returns_error(self, mock_session: mock.MagicMock) -> None:
        import requests

        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        valid, message = validate_credentials("jwt", "v2")
        assert valid is False
        assert message == "boom"


class TestTips:
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
    def test_unexpected_body_shape_fails_loud(self, MockSession: mock.MagicMock) -> None:
        # A bare array where {"docs": [...]} is expected must raise, not silently sync 0 rows.
        session = MockSession.return_value
        _wire(session, [_response([_tip(1)])])

        with pytest.raises(ValueError, match="data_selector"):
            _rows(_source("tips", _make_manager()))


class TestActivities:
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


class TestStreamElementsSourceResponse:
    @pytest.mark.parametrize("config", list(STREAMELEMENTS_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        if config.partition_key:
            assert config.partition_key == "createdAt"
