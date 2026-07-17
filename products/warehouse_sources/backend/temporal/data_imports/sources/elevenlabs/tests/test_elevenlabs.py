import os
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs import elevenlabs
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ElevenLabsResumeConfig,
    _build_params,
    _to_unix_seconds,
    elevenlabs_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import ELEVENLABS_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: ElevenLabsResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ElevenLabsResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ElevenLabsResumeConfig | None:
        return self._state

    def save_state(self, data: ElevenLabsResumeConfig) -> None:
        self.saved.append(data)


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


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 500),
            ("bad_gateway", 502),
        ]
    )
    def test_retryable_status_codes_are_retried(self, _name: str, status_code: int) -> None:
        retryable = MagicMock(status_code=status_code, ok=False)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"history": []}
        session = MagicMock()
        session.get.side_effect = [retryable, good]

        with patch.object(elevenlabs._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = elevenlabs._fetch_page(session, "https://api.elevenlabs.io/v1/history", {}, {}, MagicMock())

        assert result == {"history": []}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
            ("chunked", requests.exceptions.ChunkedEncodingError("Connection broken")),
        ]
    )
    def test_transient_network_errors_are_retried(self, _name: str, transient: Exception) -> None:
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"history": []}
        session = MagicMock()
        session.get.side_effect = [transient, good]

        with patch.object(elevenlabs._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = elevenlabs._fetch_page(session, "https://api.elevenlabs.io/v1/history", {}, {}, MagicMock())

        assert result == {"history": []}
        assert session.get.call_count == 2

    def test_credential_error_raises_without_retry(self) -> None:
        # 401 is a credential problem; retrying wastes the whole retry budget on a doomed request.
        resp = MagicMock(status_code=401, ok=False, text="unauthorized")
        resp.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized for url: https://api.elevenlabs.io/v1/history", response=resp
        )
        session = MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError):
            elevenlabs._fetch_page(session, "https://api.elevenlabs.io/v1/history", {}, {}, MagicMock())

        assert session.get.call_count == 1


class TestGetRowsPagination:
    @staticmethod
    def _run(manager: _FakeResumableManager, pages: dict[Any, dict], **incremental: Any) -> list[dict]:
        def fake_fetch(session: Any, url: str, params: dict, headers: dict, logger: Any) -> dict:
            return pages[params.get("start_after_history_item_id")]

        with patch.object(elevenlabs, "_fetch_page", fake_fetch):
            return [
                row
                for batch in get_rows("k", "history", MagicMock(), manager, **incremental)  # type: ignore[arg-type]
                for row in batch
            ]

    def test_walks_cursor_pages_and_saves_state_after_each_yield(self) -> None:
        pages = {
            None: {"history": [{"history_item_id": "a"}], "has_more": True, "last_history_item_id": "a"},
            "a": {"history": [{"history_item_id": "b"}], "has_more": False, "last_history_item_id": "b"},
        }
        manager = _FakeResumableManager()
        rows = self._run(manager, pages)

        assert rows == [{"history_item_id": "a"}, {"history_item_id": "b"}]
        # Saved only once (after page 1, since page 2 is terminal) so a crash re-yields the last page.
        assert [s.cursor for s in manager.saved] == ["a"]

    def test_terminates_when_has_more_false_even_with_a_cursor(self) -> None:
        # A stale next cursor with has_more=False must not loop forever.
        pages = {None: {"history": [{"history_item_id": "a"}], "has_more": False, "last_history_item_id": "a"}}
        rows = self._run(_FakeResumableManager(), pages)
        assert rows == [{"history_item_id": "a"}]

    def test_resumes_from_saved_cursor(self) -> None:
        def fake_fetch(session: Any, url: str, params: dict, headers: dict, logger: Any) -> dict:
            assert params["cursor"] == "C1"
            return {"conversations": [{"conversation_id": "x"}], "has_more": False, "next_cursor": None}

        manager = _FakeResumableManager(ElevenLabsResumeConfig(cursor="C1"))
        with patch.object(elevenlabs, "_fetch_page", fake_fetch):
            rows = [row for batch in get_rows("k", "conversations", MagicMock(), manager) for row in batch]  # type: ignore[arg-type]

        assert rows == [{"conversation_id": "x"}]


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
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        resp = MagicMock(status_code=status)
        with patch.object(elevenlabs, "make_tracked_session") as mts:
            mts.return_value.get.return_value = resp
            ok, _msg = validate_credentials("k", schema_name)
        assert ok is expected_ok

    def test_network_error_is_not_valid(self) -> None:
        with patch.object(elevenlabs, "make_tracked_session") as mts:
            mts.return_value.get.side_effect = requests.ConnectionError("boom")
            ok, msg = validate_credentials("k")
        assert ok is False
        assert msg is not None

    def test_session_does_not_follow_redirects(self) -> None:
        # requests keeps the custom xi-api-key header across a cross-origin 3xx; following one would
        # replay the key to the redirect target, so the credentialed session must refuse redirects.
        with patch.object(elevenlabs, "make_tracked_session") as mts:
            mts.return_value.get.return_value = MagicMock(status_code=200)
            validate_credentials("k")
        assert mts.call_args.kwargs["allow_redirects"] is False


class TestGetRowsSecurity:
    def test_session_does_not_follow_redirects(self) -> None:
        # Same key-leak boundary as validation: the sync session must not forward xi-api-key on a 3xx.
        page = {"history": [], "has_more": False, "last_history_item_id": None}
        with (
            patch.object(elevenlabs, "make_tracked_session") as mts,
            patch.object(elevenlabs, "_fetch_page", lambda *_a, **_k: page),
        ):
            list(get_rows("k", "history", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]
        assert mts.call_args.kwargs["allow_redirects"] is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("history", ["history_item_id"], "asc", "date_unix"),
            ("conversations", ["conversation_id"], "desc", "start_time_unix_secs"),
            ("agents", ["agent_id"], "asc", "created_at_unix_secs"),
            ("voices", ["voice_id"], "asc", "created_at_unix"),
        ]
    )
    def test_response_shape_per_endpoint(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str
    ) -> None:
        # sort_mode="asc" on a newest-first endpoint corrupts the watermark; the pk must be table-unique.
        response = elevenlabs_source("k", endpoint, MagicMock(), MagicMock())
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
