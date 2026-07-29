import os
import json
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ElevenLabsResumeConfig,
    _build_params,
    _to_unix_seconds,
    elevenlabs_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import ELEVENLABS_ENDPOINTS

# The RESTClient uses the session built by make_tracked_session in the elevenlabs module (passed via
# the client config's `session` slot), and validate_credentials builds its probe session there too.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs.make_tracked_session"
)


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.elevenlabs.io/v1/history"
    return resp


def _make_manager(resume_state: ElevenLabsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages (the paginator injects the next
    cursor into it), so inspecting it after the run shows only the final state — snapshot a copy when
    each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **incremental: Any):
    return elevenlabs_source("k", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **incremental)


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("int_passthrough", 1700000000, 1700000000),
            ("datetime", datetime(2024, 1, 1, tzinfo=UTC), 1704067200),
            ("numeric_string", "1700000000", 1700000000),
        ]
    )
    def test_to_unix_seconds(self, _name: str, value: Any, expected: int) -> None:
        assert _to_unix_seconds(value) == expected

    def test_naive_values_are_interpreted_as_utc_regardless_of_server_tz(self) -> None:
        # A local-time interpretation would shift the incremental watermark by the server's UTC offset,
        # so the same date would sync different windows on different machines. Force a non-UTC zone and
        # assert both a `date` and a naive `datetime` still resolve to the UTC epoch.
        original_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            assert _to_unix_seconds(date(2024, 1, 1)) == 1704067200
            assert _to_unix_seconds(datetime(2024, 1, 1)) == 1704067200
        finally:
            if original_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original_tz
            time.tzset()


class TestBuildParams:
    def test_history_incremental_sets_date_after_unix_and_asc_sort(self) -> None:
        # Wrong param name / dropped filter would silently turn every incremental sync into a full refresh.
        params = _build_params(ELEVENLABS_ENDPOINTS["history"], True, 1700000000, "date_unix")
        assert params["date_after_unix"] == 1700000000
        assert params["sort_direction"] == "asc"
        assert params["page_size"] == 1000

    def test_first_sync_applies_no_incremental_filter(self) -> None:
        # A None watermark must not build date_after_unix=None; first sync pulls full history.
        params = _build_params(ELEVENLABS_ENDPOINTS["history"], True, None, "date_unix")
        assert "date_after_unix" not in params

    def test_conversations_incremental_uses_call_start_after_unix_with_summary(self) -> None:
        params = _build_params(ELEVENLABS_ENDPOINTS["conversations"], True, 1700000000, "start_time_unix_secs")
        assert params["call_start_after_unix"] == 1700000000
        assert params["summary_mode"] == "include"

    @parameterized.expand([("agents",), ("voices",)])
    def test_full_refresh_endpoints_never_send_a_time_filter(self, endpoint: str) -> None:
        # Full-refresh endpoints have no server-side updated-since filter; sending one would 4xx.
        params = _build_params(ELEVENLABS_ENDPOINTS[endpoint], True, 1700000000, "created_at_unix")
        assert not any("after_unix" in key for key in params)

    def test_mismatched_incremental_field_does_not_filter(self) -> None:
        # The user's chosen cursor column must gate the filter, not the endpoint default.
        params = _build_params(ELEVENLABS_ENDPOINTS["history"], True, 1700000000, "something_else")
        assert "date_after_unix" not in params


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_walks_cursor_pages_and_saves_state_after_each_yield(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"history": [{"history_item_id": "a"}], "has_more": True, "last_history_item_id": "a"}),
                _response({"history": [{"history_item_id": "b"}], "has_more": False, "last_history_item_id": "b"}),
            ],
        )
        manager = _make_manager()
        rows = _rows(_source("history", manager))

        assert rows == [{"history_item_id": "a"}, {"history_item_id": "b"}]
        # Page 1 sends no cursor; page 2 sends the cursor from page 1 under the endpoint's cursor param.
        assert "start_after_history_item_id" not in params[0]
        assert params[0]["page_size"] == 1000
        assert params[1]["start_after_history_item_id"] == "a"
        # Saved only once (after page 1, since page 2 is terminal) so a crash re-yields the last page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ElevenLabsResumeConfig(cursor="a")

    @mock.patch(SESSION_PATCH)
    def test_terminates_when_has_more_false_even_with_a_cursor(self, MockSession) -> None:
        # A stale next cursor with has_more=False must not trigger another request.
        session = MockSession.return_value
        _wire(
            session,
            [_response({"history": [{"history_item_id": "a"}], "has_more": False, "last_history_item_id": "a"})],
        )
        manager = _make_manager()
        rows = _rows(_source("history", manager))

        assert rows == [{"history_item_id": "a"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [_response({"conversations": [{"conversation_id": "x"}], "has_more": False, "next_cursor": None})],
        )
        manager = _make_manager(ElevenLabsResumeConfig(cursor="C1"))
        rows = _rows(_source("conversations", manager))

        assert rows == [{"conversation_id": "x"}]
        # The resumed run starts at the saved cursor, sent under the conversations cursor param.
        assert params[0]["cursor"] == "C1"

    @mock.patch(SESSION_PATCH)
    def test_incremental_filter_reaches_the_request(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [_response({"history": [{"history_item_id": "a"}], "has_more": False, "last_history_item_id": "a"})],
        )
        _rows(
            _source(
                "history",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="date_unix",
            )
        )
        assert params[0]["date_after_unix"] == 1700000000

    @mock.patch(SESSION_PATCH)
    def test_missing_items_key_yields_no_rows_without_raising(self, MockSession) -> None:
        # A 200 body without the endpoint's array key is a legit zero-row page, not a hard error.
        session = MockSession.return_value
        _wire(session, [_response({"has_more": False})])
        rows = _rows(_source("history", _make_manager()))
        assert rows == []

    @mock.patch("time.sleep", lambda *_a, **_k: None)
    @mock.patch(SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, MockSession) -> None:
        # 429/5xx are transient; the shared transport retries them and the page eventually lands.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status=503),
                _response({"history": [{"history_item_id": "a"}], "has_more": False, "last_history_item_id": "a"}),
            ],
        )
        rows = _rows(_source("history", _make_manager()))
        assert rows == [{"history_item_id": "a"}]
        assert session.send.call_count == 2

    @mock.patch(SESSION_PATCH)
    def test_credential_error_fails_loud(self, MockSession) -> None:
        # A 401 is a doomed credential problem; it must raise (feeding get_non_retryable_errors), not retry.
        session = MockSession.return_value
        _wire(session, [_response({}, status=401)])
        with pytest.raises(requests.HTTPError):
            _rows(_source("history", _make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, None, True),
            ("bad_key", 401, None, False),
            ("missing_scope_at_create", 403, None, True),
            ("missing_scope_at_schema", 403, "history", False),
            # An unverified key (transient 429/5xx) must not be saved as valid at create time.
            ("rate_limited_at_create", 429, None, False),
            ("server_error_at_create", 500, None, False),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool, mts) -> None:
        mts.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, _msg = validate_credentials("k", schema_name)
        assert ok is expected_ok

    @mock.patch(SESSION_PATCH)
    def test_network_error_is_not_valid(self, mts) -> None:
        mts.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, msg = validate_credentials("k")
        assert ok is False
        assert msg is not None

    @mock.patch(SESSION_PATCH)
    def test_session_does_not_follow_redirects(self, mts) -> None:
        # requests keeps the custom xi-api-key header across a cross-origin 3xx; following one would
        # replay the key to the redirect target, so the credentialed session must refuse redirects.
        mts.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("k")
        assert mts.call_args.kwargs["allow_redirects"] is False


class TestSyncSecurity:
    @mock.patch(SESSION_PATCH)
    def test_sync_session_does_not_follow_redirects(self, MockSession) -> None:
        # Same key-leak boundary as validation: the sync session must not forward xi-api-key on a 3xx.
        session = MockSession.return_value
        _wire(session, [_response({"history": [], "has_more": False, "last_history_item_id": None})])
        _rows(_source("history", _make_manager()))
        assert any(call.kwargs.get("allow_redirects") is False for call in MockSession.call_args_list)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("history", ["history_item_id"], "asc", "date_unix"),
            ("conversations", ["conversation_id"], "desc", "start_time_unix_secs"),
            ("agents", ["agent_id"], "asc", "created_at_unix_secs"),
            ("voices", ["voice_id"], "asc", "created_at_unix"),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_response_shape_per_endpoint(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str, _mts
    ) -> None:
        # sort_mode="asc" on a newest-first endpoint corrupts the watermark; the pk must be table-unique.
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
