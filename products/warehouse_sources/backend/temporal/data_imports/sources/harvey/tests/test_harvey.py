import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.harvey import (
    HarveyResumeConfig,
    HarveyRetryableError,
    _fetch_json,
    _parse_datetime,
    _to_epoch,
    check_endpoint_access,
    get_base_url,
    get_rows,
    harvey_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.settings import (
    AUDIT_LOGS_PAGE_SIZE,
    MAX_LOOKBACK_DAYS,
)

NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
NOW_EPOCH = int(NOW.timestamp())

HARVEY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.harvey"

# The undecorated function behind tenacity's retry wrapper, so failure-path tests don't sit
# through the backoff schedule. mypy can't see tenacity's `__wrapped__`, hence the cast.
_fetch_json_unretried = cast(Any, _fetch_json).__wrapped__


class _FakeManager:
    def __init__(self, resume: HarveyResumeConfig | None = None) -> None:
        self._resume = resume
        self.saved: list[HarveyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> HarveyResumeConfig | None:
        return self._resume

    def save_state(self, data: HarveyResumeConfig) -> None:
        self.saved.append(data)


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.harvey.ai/api/test"
    return resp


def _session_with(responses: list[Response]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = responses
    return session


def _requested_urls(session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


def _query_params(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def _audit_log(log_id: str, timestamp: str = "2026-06-01T10:00:00+00:00") -> dict[str, Any]:
    return {
        "id": log_id,
        "timestamp": timestamp,
        "type": "auth:login",
        "user": "user@example.com",
        "ip": "203.0.113.10",
        "user_agent": "curl/8.0",
        "data": {},
    }


def _history_event(usage_id: str, utc_time: str = "2026-07-01 10:30:00") -> dict[str, Any]:
    return {
        "unique_usage_id": usage_id,
        "utc_time": utc_time,
        "user": "user@example.com",
        "product_surface_area": "ASSISTANT",
        "metadata": {},
    }


class TestHelpers:
    @parameterized.expand(
        [
            ("us", "us", "https://api.harvey.ai"),
            ("eu", "eu", "https://eu.api.harvey.ai"),
            ("au", "au", "https://au.api.harvey.ai"),
            ("uppercase", "US", "https://api.harvey.ai"),
            ("none", None, "https://api.harvey.ai"),
            ("unknown", "unknown", "https://api.harvey.ai"),
        ]
    )
    def test_get_base_url(self, _name: str, region: str | None, expected: str) -> None:
        assert get_base_url(region) == expected

    @parameterized.expand(
        [
            ("iso_offset", "2026-06-01T10:00:00+00:00", datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)),
            ("iso_z", "2026-06-01T10:00:00Z", datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)),
            ("space_separated", "2026-02-22 14:01:23", datetime(2026, 2, 22, 14, 1, 23, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 6, 1, 10, 0, 0), datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)),
            ("unparseable_string", "not a timestamp", None),
            ("none", None, None),
            ("int", 12345, None),
        ]
    )
    def test_parse_datetime(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert _parse_datetime(value) == expected

    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC), NOW_EPOCH),
            ("naive_datetime", datetime(2026, 7, 1, 12, 0, 0), NOW_EPOCH),
            ("date", date(2026, 7, 1), NOW_EPOCH - 12 * 60 * 60),
            ("int", NOW_EPOCH, NOW_EPOCH),
            ("float", float(NOW_EPOCH), NOW_EPOCH),
            ("iso_string", "2026-07-01T12:00:00+00:00", NOW_EPOCH),
        ]
    )
    def test_to_epoch(self, _name: str, value: Any, expected: int) -> None:
        assert _to_epoch(value) == expected

    def test_to_epoch_rejects_unparseable_values(self) -> None:
        with pytest.raises(ValueError):
            _to_epoch("not a timestamp")

    @parameterized.expand([("throttle", 429), ("server_error", 500), ("unavailable", 503)])
    def test_fetch_json_raises_retryable_on_throttle_and_server_errors(self, _name: str, status_code: int) -> None:
        session = _session_with([_response({}, status_code=status_code)])
        with pytest.raises(HarveyRetryableError):
            _fetch_json_unretried(session, "https://api.harvey.ai/api/test", {}, mock.MagicMock())

    def test_fetch_json_raises_http_error_on_client_errors(self) -> None:
        session = _session_with([_response({"error": "Unauthorized"}, status_code=401)])
        with pytest.raises(HTTPError):
            _fetch_json_unretried(session, "https://api.harvey.ai/api/test", {}, mock.MagicMock())


class TestValidateCredentials:
    @parameterized.expand(
        [("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)],
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = _session_with([_response({}, status_code=status_code)])
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("token", "us") is expected

        assert _requested_urls(session) == ["https://api.harvey.ai/api/whoami"]

    def test_uses_regional_base_url(self) -> None:
        session = _session_with([_response({})])
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            validate_credentials("token", "eu")

        assert _requested_urls(session) == ["https://eu.api.harvey.ai/api/whoami"]

    def test_network_error_is_invalid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("boom")
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("token", "us") is False


class TestCheckEndpointAccess:
    @parameterized.expand(
        [
            ("audit_logs", "audit_logs", "/api/v1/logs/audit/latest"),
            ("usage_history", "usage_history", "/api/v2/history/usage"),
            ("query_history", "query_history", "/api/v2/history/query"),
            ("client_matters", "client_matters", "/api/v1/client_matters"),
            ("vault_projects", "vault_projects", "/api/v1/vault/workspace/projects"),
        ]
    )
    def test_probes_the_right_endpoint(self, _name: str, endpoint: str, expected_path: str) -> None:
        session = _session_with([_response({})])
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            assert check_endpoint_access("token", "us", endpoint) is None

        assert expected_path in _requested_urls(session)[0]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_denial_returns_reason(self, _name: str, status_code: int) -> None:
        session = _session_with([_response({}, status_code=status_code)])
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            reason = check_endpoint_access("token", "us", "audit_logs")

        assert reason is not None
        assert "permission" in reason

    @parameterized.expand([("not_found", 404), ("throttle", 429), ("server_error", 500)])
    def test_non_denial_statuses_are_reachable(self, _name: str, status_code: int) -> None:
        session = _session_with([_response({}, status_code=status_code)])
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            assert check_endpoint_access("token", "us", "audit_logs") is None

    def test_network_error_is_reachable(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("boom")
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            assert check_endpoint_access("token", "us", "audit_logs") is None


class TestSessionRedaction:
    # A dropped `redact_values` would copy the bearer token into captured request samples and logged
    # errors, leaking the credential into warehouse job telemetry. Every request-issuing entry point
    # must build its session with the token registered for redaction.
    @parameterized.expand(
        [
            ("validate_credentials", lambda: validate_credentials("token", "us")),
            ("check_endpoint_access", lambda: check_endpoint_access("token", "us", "audit_logs")),
            (
                "get_rows",
                lambda: list(
                    get_rows(
                        api_key="token",
                        region="us",
                        endpoint="client_matters",
                        logger=mock.MagicMock(),
                        resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
                    )
                ),
            ),
        ]
    )
    def test_tracked_session_redacts_api_token(self, _name: str, run: Callable[[], Any]) -> None:
        session = _session_with([_response({})])
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session) as mock_session:
            run()

        assert mock_session.call_args.kwargs["redact_values"] == ("token",)


class TestAuditLogRows:
    def _get_batches(
        self,
        responses: list[Response],
        manager: _FakeManager,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        session = _session_with(responses)
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    api_key="token",
                    region="us",
                    endpoint="audit_logs",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return batches, session

    def test_full_sync_seeds_from_earliest(self) -> None:
        manager = _FakeManager()
        batches, session = self._get_batches(
            [
                _response({"log": _audit_log("log-a")}),
                _response([_audit_log("log-b"), _audit_log("log-c")]),
            ],
            manager,
        )

        # The seed log is yielded on its own (the `from` param is exclusive), then the page.
        assert [[log["id"] for log in batch] for batch in batches] == [["log-a"], ["log-b", "log-c"]]

        urls = _requested_urls(session)
        assert urls[0] == "https://api.harvey.ai/api/v1/logs/audit/earliest"
        assert _query_params(urls[1]) == {"from": "log-a", "take": str(AUDIT_LOGS_PAGE_SIZE)}

        # State is saved after each yielded batch, bookmarking the last processed id.
        assert [state.last_audit_log_id for state in manager.saved] == ["log-a", "log-c"]

    def test_full_sync_no_logs(self) -> None:
        manager = _FakeManager()
        batches, session = self._get_batches([_response({"error": "Not found"}, status_code=404)], manager)

        assert batches == []
        assert manager.saved == []

    def test_full_page_keeps_paginating(self) -> None:
        full_page = [_audit_log(f"log-{i}") for i in range(AUDIT_LOGS_PAGE_SIZE)]
        manager = _FakeManager()
        batches, session = self._get_batches(
            [
                _response({"log": _audit_log("log-seed")}),
                _response(full_page),
                _response([]),
            ],
            manager,
        )

        assert len(batches) == 2
        urls = _requested_urls(session)
        assert _query_params(urls[2])["from"] == f"log-{AUDIT_LOGS_PAGE_SIZE - 1}"

    @freeze_time(NOW)
    def test_incremental_seeds_from_search(self) -> None:
        last_value = datetime(2026, 6, 30, 9, 0, 0, tzinfo=UTC)
        manager = _FakeManager()
        batches, session = self._get_batches(
            [
                _response({"log": _audit_log("log-a")}),
                _response([_audit_log("log-b")]),
            ],
            manager,
            db_incremental_field_last_value=last_value,
        )

        urls = _requested_urls(session)
        assert urls[0].startswith("https://api.harvey.ai/api/v1/logs/audit/search?")
        assert _query_params(urls[0]) == {"time": str(int(last_value.timestamp()))}
        assert [[log["id"] for log in batch] for batch in batches] == [["log-a"], ["log-b"]]

    @freeze_time(NOW)
    def test_incremental_caught_up(self) -> None:
        # No log at or after the watermark - the search endpoint 404s.
        manager = _FakeManager()
        batches, _ = self._get_batches(
            [_response({"error": "Not found"}, status_code=404)],
            manager,
            db_incremental_field_last_value=NOW,
        )

        assert batches == []

    @freeze_time(NOW)
    def test_incremental_watermark_older_than_search_limit_falls_back_to_earliest(self) -> None:
        stale_watermark = datetime(2024, 1, 1, tzinfo=UTC)
        manager = _FakeManager()
        _, session = self._get_batches(
            [
                _response({"log": _audit_log("log-a")}),
                _response([]),
            ],
            manager,
            db_incremental_field_last_value=stale_watermark,
        )

        assert _requested_urls(session)[0] == "https://api.harvey.ai/api/v1/logs/audit/earliest"

    def test_resume_skips_seeding(self) -> None:
        manager = _FakeManager(resume=HarveyResumeConfig(last_audit_log_id="log-x"))
        batches, session = self._get_batches([_response([_audit_log("log-y")])], manager)

        urls = _requested_urls(session)
        assert _query_params(urls[0])["from"] == "log-x"
        assert [[log["id"] for log in batch] for batch in batches] == [["log-y"]]

    def test_timestamps_are_parsed_to_datetimes(self) -> None:
        manager = _FakeManager()
        batches, _ = self._get_batches(
            [
                _response({"log": _audit_log("log-a", timestamp="2026-06-01T10:00:00Z")}),
                _response([]),
            ],
            manager,
        )

        assert batches[0][0]["timestamp"] == datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)


class TestHistoryRows:
    def _get_batches(
        self,
        responses: list[Response],
        manager: _FakeManager,
        endpoint: str = "usage_history",
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        session = _session_with(responses)
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    api_key="token",
                    region="us",
                    endpoint=endpoint,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return batches, session

    @parameterized.expand(
        [
            ("usage_history", "usage_history", "/api/v2/history/usage"),
            ("query_history", "query_history", "/api/v2/history/query"),
        ]
    )
    @freeze_time(NOW)
    def test_incremental_fetches_windows_up_to_now(self, _name: str, endpoint: str, expected_path: str) -> None:
        last_value = datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC)
        manager = _FakeManager()
        batches, session = self._get_batches(
            [_response({"events": [_history_event("usage-1")]})],
            manager,
            endpoint=endpoint,
            db_incremental_field_last_value=last_value,
        )

        urls = _requested_urls(session)
        assert expected_path in urls[0]
        assert _query_params(urls[0]) == {
            "start_time": str(int(last_value.timestamp())),
            "end_time": str(NOW_EPOCH),
        }
        assert [[event["unique_usage_id"] for event in batch] for batch in batches] == [["usage-1"]]
        # utc_time is parsed so the incremental watermark and partitioning see a datetime.
        assert batches[0][0]["utc_time"] == datetime(2026, 7, 1, 10, 30, 0, tzinfo=UTC)
        assert [state.window_start for state in manager.saved] == [NOW_EPOCH]

    @freeze_time(NOW)
    def test_walks_multiple_windows_and_saves_state_after_each(self) -> None:
        # 2.5 windows back from now: expect 3 requests covering contiguous ranges.
        last_value = NOW_EPOCH - int(2.5 * 24 * 60 * 60)
        manager = _FakeManager()
        batches, session = self._get_batches(
            [
                _response({"events": [_history_event("usage-1", utc_time="2026-06-29 03:00:00")]}),
                _response({"events": []}),
                _response({"events": [_history_event("usage-2", utc_time="2026-07-01 11:00:00")]}),
            ],
            manager,
            db_incremental_field_last_value=last_value,
        )

        params = [_query_params(url) for url in _requested_urls(session)]
        day = 24 * 60 * 60
        assert [(p["start_time"], p["end_time"]) for p in params] == [
            (str(last_value), str(last_value + day)),
            (str(last_value + day), str(last_value + 2 * day)),
            (str(last_value + 2 * day), str(NOW_EPOCH)),
        ]
        # The empty middle window yields nothing but still advances the saved cursor.
        assert len(batches) == 2
        assert [state.window_start for state in manager.saved] == [
            last_value + day,
            last_value + 2 * day,
            NOW_EPOCH,
        ]

    @freeze_time(NOW)
    def test_full_sync_starts_at_lookback_floor(self) -> None:
        manager = _FakeManager()
        # Widen the window so the full backfill is a single request.
        with mock.patch(f"{HARVEY_MODULE}.HISTORY_WINDOW_SECONDS", 400 * 24 * 60 * 60):
            _, session = self._get_batches([_response({"events": []})], manager)

        params = _query_params(_requested_urls(session)[0])
        assert params["start_time"] == str(NOW_EPOCH - MAX_LOOKBACK_DAYS * 24 * 60 * 60)
        assert params["end_time"] == str(NOW_EPOCH)

    @freeze_time(NOW)
    def test_incremental_caught_up_makes_no_requests(self) -> None:
        manager = _FakeManager()
        batches, session = self._get_batches([], manager, db_incremental_field_last_value=NOW)

        assert batches == []
        assert session.get.call_count == 0

    @freeze_time(NOW)
    def test_resume_starts_at_saved_window(self) -> None:
        window_start = NOW_EPOCH - 3600
        manager = _FakeManager(resume=HarveyResumeConfig(window_start=window_start))
        _, session = self._get_batches([_response({"events": []})], manager)

        assert _query_params(_requested_urls(session)[0])["start_time"] == str(window_start)

    @freeze_time(NOW)
    def test_incremental_watermark_older_than_api_limit_is_clamped(self) -> None:
        manager = _FakeManager()
        with mock.patch(f"{HARVEY_MODULE}.HISTORY_WINDOW_SECONDS", 400 * 24 * 60 * 60):
            _, session = self._get_batches(
                [_response({"events": []})],
                manager,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            )

        params = _query_params(_requested_urls(session)[0])
        assert params["start_time"] == str(NOW_EPOCH - MAX_LOOKBACK_DAYS * 24 * 60 * 60)


class TestClientMatterRows:
    def _get_batches(self, responses: list[Response]) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        session = _session_with(responses)
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    api_key="token",
                    region="us",
                    endpoint="client_matters",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
                )
            )
        return batches, session

    def test_single_unpaginated_fetch(self) -> None:
        matters = [
            {"id": "cm-1", "name": "1234-5678", "user_count": 3},
            {"id": "cm-2", "name": "8765-4321", "user_count": 1},
        ]
        batches, session = self._get_batches([_response(matters)])

        assert batches == [matters]
        assert _requested_urls(session) == ["https://api.harvey.ai/api/v1/client_matters"]

    def test_empty_list_yields_nothing(self) -> None:
        batches, _ = self._get_batches([_response([])])
        assert batches == []


class TestVaultProjectRows:
    def _vault_page(self, project_ids: list[str], page: int, total_pages: int) -> Response:
        return _response(
            {
                "response": {
                    "content": {
                        "projects": [{"id": project_id, "name": project_id} for project_id in project_ids],
                        "pagination": {"page": page, "per_page": 100, "total": 0, "total_pages": total_pages},
                    }
                }
            }
        )

    def _get_batches(
        self, responses: list[Response], manager: _FakeManager
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        session = _session_with(responses)
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    api_key="token",
                    region="us",
                    endpoint="vault_projects",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )
        return batches, session

    def test_single_page(self) -> None:
        manager = _FakeManager()
        batches, session = self._get_batches([self._vault_page(["proj-1", "proj-2"], page=1, total_pages=1)], manager)

        assert [[p["id"] for p in batch] for batch in batches] == [["proj-1", "proj-2"]]
        params = _query_params(_requested_urls(session)[0])
        # Name sort keeps pagination stable; the default date sort reshuffles mid-walk.
        assert params["sort_by"] == "name"
        assert params["sort_order"] == "asc"
        assert manager.saved == []

    def test_multiple_pages_save_state_between_pages(self) -> None:
        manager = _FakeManager()
        batches, session = self._get_batches(
            [
                self._vault_page(["proj-1"], page=1, total_pages=2),
                self._vault_page(["proj-2"], page=2, total_pages=2),
            ],
            manager,
        )

        assert len(batches) == 2
        assert _query_params(_requested_urls(session)[1])["page"] == "2"
        assert [state.next_page for state in manager.saved] == [2]

    def test_resume_starts_at_saved_page(self) -> None:
        manager = _FakeManager(resume=HarveyResumeConfig(next_page=3))
        _, session = self._get_batches([self._vault_page([], page=3, total_pages=5)], manager)

        assert _query_params(_requested_urls(session)[0])["page"] == "3"

    def test_empty_page_stops(self) -> None:
        manager = _FakeManager()
        batches, _ = self._get_batches([self._vault_page([], page=1, total_pages=0)], manager)
        assert batches == []


class TestHarveySourceResponse:
    @parameterized.expand(
        [
            ("audit_logs", "audit_logs", ["id"], ["timestamp"]),
            ("usage_history", "usage_history", ["unique_usage_id"], ["utc_time"]),
            ("query_history", "query_history", ["unique_usage_id"], ["utc_time"]),
            ("client_matters", "client_matters", ["id"], None),
            ("vault_projects", "vault_projects", ["id"], None),
        ]
    )
    def test_source_response_shape(
        self, _name: str, endpoint: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        response = harvey_source(
            api_key="token",
            region="us",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        assert response.sort_mode == "asc"

    def test_unknown_endpoint_raises(self) -> None:
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=mock.MagicMock()):
            with pytest.raises(ValueError):
                list(
                    get_rows(
                        api_key="token",
                        region="us",
                        endpoint="nonexistent",
                        logger=mock.MagicMock(),
                        resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
                    )
                )
