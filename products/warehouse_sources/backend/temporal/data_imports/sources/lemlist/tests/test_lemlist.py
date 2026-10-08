import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.lemlist import (
    LEMLIST_API_VERSION_V1,
    LEMLIST_API_VERSION_V2,
    LEMLIST_DEFAULT_VERSION,
    PAGE_SIZE,
    LemlistResumeConfig,
    _clamp_future_value_to_now,
    _format_incremental_value,
    lemlist_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the lemlist module.
LEMLIST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.lemlist.make_tracked_session"
)
# tenacity sleeps between retries; patch it so the retryable-path test doesn't actually wait.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(payload: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.url = "https://api.lemlist.com/api/probe"
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: LemlistResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(
    endpoint: str,
    manager: mock.MagicMock | None = None,
    *,
    api_version: str = LEMLIST_DEFAULT_VERSION,
    **kwargs: Any,
):
    return lemlist_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        api_version=api_version,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 5, 11, 2, 58, 14, tzinfo=UTC), "2026-05-11T02:58:14Z"),
            ("naive_datetime", datetime(2026, 5, 11, 2, 58, 14), "2026-05-11T02:58:14Z"),
            ("date_value", date(2026, 5, 11), "2026-05-11T00:00:00Z"),
            ("string_passthrough", "1715385600", "1715385600"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestClampFutureValueToNow:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_date_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor") == "cursor"


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_campaigns_never_sends_mindate(self, MockSession) -> None:
        # Campaigns has no server-side date filter, so even an incremental request must not add minDate.
        session = MockSession.return_value
        params = _wire(session, [_response([{"_id": "cam_1"}])])
        _rows(
            _source(
                "campaigns",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 5, 11, tzinfo=UTC),
            )
        )
        assert "minDate" not in params[0]

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_activities_first_sync_uses_lookback_window(self, MockSession) -> None:
        # No stored watermark -> bound the first sync by the configured lookback instead of full history.
        session = MockSession.return_value
        params = _wire(session, [_response([{"_id": "act_1"}])])
        _rows(_source("activities", should_use_incremental_field=True, db_incremental_field_last_value=None))
        assert params[0]["minDate"] == "2025-06-15T12:00:00Z"


class TestVersionDispatch:
    @parameterized.expand(
        [
            # campaigns/activities only serve v2, so the param rides either pin (v1 pins byte-for-byte).
            ("campaigns_pin_v1", "campaigns", LEMLIST_API_VERSION_V1, [{"_id": "c"}], "v2"),
            ("campaigns_pin_v2", "campaigns", LEMLIST_API_VERSION_V2, [{"_id": "c"}], "v2"),
            # /team's v2 adds a users array, so version is sent only under a v2 pin.
            ("team_pin_v1", "team", LEMLIST_API_VERSION_V1, {"_id": "t"}, None),
            ("team_pin_v2", "team", LEMLIST_API_VERSION_V2, {"_id": "t"}, "v2"),
            # Endpoints with no version variant never send the param, whatever the pin.
            ("team_senders_pin_v2", "team_senders", LEMLIST_API_VERSION_V2, [{"userId": "u"}], None),
            ("unsubscribes_pin_v2", "unsubscribes", LEMLIST_API_VERSION_V2, [{"_id": "u"}], None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_param_per_endpoint_and_pin(
        self, _name: str, endpoint: str, api_version: str, payload: Any, expected: str | None, MockSession
    ) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(payload)])
        _rows(_source(endpoint, api_version=api_version))
        assert params[0].get("version") == expected


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("not_found", 404, False)])
    @mock.patch(LEMLIST_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key") is expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"_id": f"cam_{i}"} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"_id": "cam_last"}])])
        manager = _make_manager()
        rows = _rows(_source("campaigns", manager))
        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"_id": "cam_last"}
        assert params[0]["offset"] == 0
        assert params[1]["offset"] == PAGE_SIZE
        # State is saved once, after the first full page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == LemlistResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"_id": "cam_resumed"}])])
        manager = _make_manager(LemlistResumeConfig(offset=PAGE_SIZE))
        rows = _rows(_source("campaigns", manager))
        assert rows == [{"_id": "cam_resumed"}]
        assert params[0]["offset"] == PAGE_SIZE


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        # A 429/5xx is retried by the client; a subsequent success completes the sync.
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status_code), _response([{"_id": "cam_1"}])])
        rows = _rows(_source("campaigns"))
        assert rows == [{"_id": "cam_1"}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_and_is_not_retried(self, MockSession) -> None:
        # A 4xx (other than 429) is a permanent error surfaced via raise_for_status — no retry.
        session = MockSession.return_value
        _wire(session, [_response({"error": "unauthorized"}, status_code=401)])
        with pytest.raises(requests.HTTPError):
            _rows(_source("campaigns"))
        assert session.send.call_count == 1
