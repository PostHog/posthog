from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot import uptimerobot
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.settings import (
    PAGE_LIMIT,
    RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS,
    UPTIMEROBOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.uptimerobot import (
    AUTH_ERROR_PREFIX,
    UptimeRobotAPIError,
    UptimeRobotAuthError,
    UptimeRobotResumeConfig,
    UptimeRobotRetryableError,
    _next_offset,
    _post,
    _scrub_alert_contact,
    _to_unix_timestamp,
    get_rows,
    uptimerobot_source,
)

_DAY = 86400


class TestToUnixTimestamp:
    @parameterized.expand(
        [
            ("int_epoch", 1750000000, 1750000000),
            ("float_epoch", 1750000000.9, 1750000000),
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094),
            ("naive_datetime_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), 1772593094),
            ("date_value", date(2026, 3, 4), 1772582400),
            ("numeric_string", "1750000000", 1750000000),
            ("iso_string", "2026-03-04T02:58:14+00:00", 1772593094),
            ("iso_string_z_suffix", "2026-03-04T02:58:14Z", 1772593094),
            ("junk_string", "not-a-date", None),
            ("empty_string", "", None),
            ("none_value", None, None),
            ("bool_value", True, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_unix_timestamp(value) == expected


class TestScrubAlertContact:
    @parameterized.expand(
        [
            # Credential-bearing channels: value is a URL/token that could forge notifications.
            ("webhook", 5, "https://hooks.example.com/abc?token=s3cret", None),
            ("slack", 11, "https://hooks.slack.com/services/T/B/xox", None),
            ("unknown_integration", 99, "https://integration.example.com/tok", None),
            # Fail closed when the type is missing or non-numeric.
            ("missing_type", None, "https://hooks.example.com/abc?token=s3cret", None),
            ("non_numeric_type", "webhook", "https://hooks.example.com/abc?token=s3cret", None),
            # Plain destinations: kept for analytical use.
            ("sms", 1, "+15551234567", "+15551234567"),
            ("email", 2, "ops@example.com", "ops@example.com"),
            ("twitter", 3, "@statuspage", "@statuspage"),
        ]
    )
    def test_value_redacted_unless_plain_destination(
        self, _name: str, contact_type: Any, value: str, expected_value: str | None
    ) -> None:
        row: dict[str, Any] = {"id": 1, "friendly_name": "on-call", "status": 2, "value": value}
        if contact_type is not None:
            row["type"] = contact_type

        scrubbed = _scrub_alert_contact(row)

        assert scrubbed["value"] == expected_value
        # Non-secret metadata is always preserved.
        assert scrubbed["id"] == 1
        assert scrubbed["friendly_name"] == "on-call"
        assert scrubbed["status"] == 2

    def test_row_without_value_is_untouched(self) -> None:
        row = {"id": 1, "type": 5}
        assert _scrub_alert_contact(row) == row


class TestNextOffset:
    @parameterized.expand(
        [
            ("nested_more_pages", {"pagination": {"offset": 0, "limit": 50, "total": 120}}, 0, 50, 50),
            ("nested_exhausted", {"pagination": {"offset": 100, "limit": 50, "total": 120}}, 100, 20, None),
            ("nested_exact_boundary", {"pagination": {"offset": 50, "limit": 50, "total": 100}}, 50, 50, None),
            # getAlertContacts puts offset/limit/total at the top level, as strings.
            ("top_level_strings_more", {"offset": "0", "limit": "50", "total": "70"}, 0, 50, 50),
            ("top_level_strings_exhausted", {"offset": "50", "limit": "50", "total": "70"}, 50, 20, None),
            ("missing_metadata_full_page", {}, 0, PAGE_LIMIT, PAGE_LIMIT),
            ("missing_metadata_partial_page", {}, 0, 5, None),
        ]
    )
    def test_next_offset(
        self, _name: str, payload: dict, requested_offset: int, page_len: int, expected: int | None
    ) -> None:
        assert _next_offset(payload, requested_offset, page_len) == expected


def _response(status_code: int = 200, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload if payload is not None else {}
    return response


class TestPost:
    def _call(self, response: MagicMock) -> dict:
        session = MagicMock()
        session.post.return_value = response
        # Call the undecorated function so tenacity's exponential backoff doesn't sleep in tests.
        return _post.__wrapped__(session, "getMonitors", {"api_key": "k"}, MagicMock())  # type: ignore[attr-defined]

    def test_ok_payload_returned(self) -> None:
        payload = {"stat": "ok", "monitors": [{"id": 1}]}
        assert self._call(_response(payload=payload)) == payload

    def test_invalid_api_key_raises_auth_error(self) -> None:
        # Verified against the live API: bad keys return HTTP 200 with an in-body error.
        payload = {
            "stat": "fail",
            "error": {"type": "invalid_parameter", "parameter_name": "api_key", "message": "api_key is invalid."},
        }
        with pytest.raises(UptimeRobotAuthError, match=AUTH_ERROR_PREFIX):
            self._call(_response(payload=payload))

    def test_other_in_body_error_raises_api_error(self) -> None:
        payload = {"stat": "fail", "error": {"type": "invalid_parameter", "parameter_name": "offset"}}
        with pytest.raises(UptimeRobotAPIError):
            self._call(_response(payload=payload))

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_transient_statuses_raise_retryable(self, _name: str, status_code: int) -> None:
        with pytest.raises(UptimeRobotRetryableError):
            self._call(_response(status_code=status_code))


class _FakeResumableManager:
    def __init__(self, state: UptimeRobotResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[UptimeRobotResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> UptimeRobotResumeConfig | None:
        return self._state

    def save_state(self, data: UptimeRobotResumeConfig) -> None:
        self.saved.append(data)


def _patch_post(monkeypatch: Any, responder: Any) -> list[dict]:
    requests_made: list[dict] = []

    def fake_post(session: Any, method: str, data: dict, logger: Any) -> dict:
        requests_made.append({"method": method, **data})
        return responder(method, data)

    monkeypatch.setattr(uptimerobot, "_post", fake_post)
    monkeypatch.setattr(uptimerobot, "make_tracked_session", lambda: MagicMock())
    return requests_made


def _collect(manager: _FakeResumableManager, endpoint: str, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestTopLevelRows:
    def test_paginates_until_total_reached(self, monkeypatch: Any) -> None:
        def responder(method: str, data: dict) -> dict:
            offset = data["offset"]
            if offset == 0:
                return {
                    "stat": "ok",
                    "pagination": {"offset": 0, "limit": 50, "total": 51},
                    "monitors": [{"id": n} for n in range(50)],
                }
            return {
                "stat": "ok",
                "pagination": {"offset": 50, "limit": 50, "total": 51},
                "monitors": [{"id": 50}],
            }

        requests_made = _patch_post(monkeypatch, responder)
        rows = _collect(_FakeResumableManager(), "monitors")

        assert [r["id"] for r in rows] == list(range(51))
        assert [r["offset"] for r in requests_made] == [0, 50]

    def test_saves_resume_state_after_yield_only_when_more_pages(self, monkeypatch: Any) -> None:
        def responder(method: str, data: dict) -> dict:
            offset = data["offset"]
            total = {"offset": offset, "limit": 50, "total": 60}
            rows = [{"id": offset}]
            return {"stat": "ok", "pagination": total, "monitors": rows}

        _patch_post(monkeypatch, responder)
        manager = _FakeResumableManager()
        _collect(manager, "monitors")

        # Saved once (before fetching page 2), never after the final page.
        assert manager.saved == [UptimeRobotResumeConfig(offset=50)]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        def responder(method: str, data: dict) -> dict:
            return {
                "stat": "ok",
                "pagination": {"offset": data["offset"], "limit": 50, "total": 100},
                "monitors": [{"id": data["offset"]}],
            }

        requests_made = _patch_post(monkeypatch, responder)
        _collect(_FakeResumableManager(UptimeRobotResumeConfig(offset=50)), "monitors")

        assert requests_made[0]["offset"] == 50

    def test_alert_contacts_top_level_string_pagination_terminates(self, monkeypatch: Any) -> None:
        def responder(method: str, data: dict) -> dict:
            assert method == "getAlertContacts"
            return {
                "stat": "ok",
                "offset": "0",
                "limit": "50",
                "total": "2",
                "alert_contacts": [{"id": "1"}, {"id": "2"}],
            }

        requests_made = _patch_post(monkeypatch, responder)
        rows = _collect(_FakeResumableManager(), "alert_contacts")

        assert [r["id"] for r in rows] == ["1", "2"]
        assert len(requests_made) == 1

    def test_monitor_credentials_are_stripped_from_rows(self, monkeypatch: Any) -> None:
        # getMonitors echoes back the monitored endpoint's HTTP Basic Auth credentials and custom
        # request headers; these must never reach the warehouse where any project member with read
        # access could recover them.
        def responder(method: str, data: dict) -> dict:
            return {
                "stat": "ok",
                "pagination": {"offset": 0, "limit": 50, "total": 1},
                "monitors": [
                    {
                        "id": 1,
                        "friendly_name": "prod",
                        "http_username": "svc",
                        "http_password": "hunter2",
                        "custom_http_headers": {"Authorization": "Bearer tok"},
                    }
                ],
            }

        _patch_post(monkeypatch, responder)
        rows = _collect(_FakeResumableManager(), "monitors")

        assert rows == [{"id": 1, "friendly_name": "prod"}]

    def test_alert_contact_webhook_value_is_redacted_end_to_end(self, monkeypatch: Any) -> None:
        # Wiring guard: the alert_contacts endpoint must apply the credential scrubber, so a webhook
        # URL embedding a secret token never reaches the warehouse where any project member with read
        # access could recover and abuse it. The type matrix is covered by TestScrubAlertContact.
        def responder(method: str, data: dict) -> dict:
            return {
                "stat": "ok",
                "offset": "0",
                "limit": "50",
                "total": "1",
                "alert_contacts": [
                    {"id": 1, "friendly_name": "on-call", "type": 5, "status": 2, "value": "https://h/x?t=s3cret"}
                ],
            }

        _patch_post(monkeypatch, responder)
        rows = _collect(_FakeResumableManager(), "alert_contacts")

        assert rows == [{"id": 1, "friendly_name": "on-call", "type": 5, "status": 2, "value": None}]

    def test_monitors_request_includes_uptime_ratio_params(self, monkeypatch: Any) -> None:
        def responder(method: str, data: dict) -> dict:
            return {"stat": "ok", "pagination": {"offset": 0, "limit": 50, "total": 0}, "monitors": []}

        requests_made = _patch_post(monkeypatch, responder)
        rows = _collect(_FakeResumableManager(), "monitors")

        assert rows == []
        assert requests_made[0]["custom_uptime_ratios"] == "1-7-30-365"
        assert requests_made[0]["all_time_uptime_ratio"] == 1


class TestMonitorLogRows:
    def _responder(self, method: str, data: dict) -> dict:
        return {
            "stat": "ok",
            "pagination": {"offset": 0, "limit": 50, "total": 2},
            "monitors": [
                {
                    "id": 1,
                    "logs": [
                        {"type": 1, "datetime": 100, "duration": 60},
                        {"type": 2, "datetime": 200, "duration": 0},
                    ],
                },
                {"id": 2, "logs": [{"type": 98, "datetime": 300, "duration": 0}]},
            ],
        }

    def test_flattens_logs_with_monitor_id(self, monkeypatch: Any) -> None:
        requests_made = _patch_post(monkeypatch, self._responder)
        rows = _collect(_FakeResumableManager(), "monitor_logs")

        assert rows == [
            {"type": 1, "datetime": 100, "duration": 60, "monitor_id": 1},
            {"type": 2, "datetime": 200, "duration": 0, "monitor_id": 1},
            {"type": 98, "datetime": 300, "duration": 0, "monitor_id": 2},
        ]
        assert requests_made[0]["logs"] == 1
        # No watermark -> no server-side log window params.
        assert "logs_start_date" not in requests_made[0]

    def test_incremental_filters_client_side_and_sends_window(self, monkeypatch: Any) -> None:
        requests_made = _patch_post(monkeypatch, self._responder)
        rows = _collect(
            _FakeResumableManager(),
            "monitor_logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=200,
        )

        # Free plans ignore logs_start_date and return every retained log; rows at or before the
        # watermark must be dropped client-side.
        assert rows == [{"type": 98, "datetime": 300, "duration": 0, "monitor_id": 2}]
        assert requests_made[0]["logs_start_date"] == 200
        assert "logs_end_date" in requests_made[0]

    def test_monitor_without_logs_key_yields_nothing(self, monkeypatch: Any) -> None:
        def responder(method: str, data: dict) -> dict:
            return {
                "stat": "ok",
                "pagination": {"offset": 0, "limit": 50, "total": 1},
                "monitors": [{"id": 1}],
            }

        _patch_post(monkeypatch, responder)
        assert _collect(_FakeResumableManager(), "monitor_logs") == []


class TestResponseTimeRows:
    NOW = 1_760_000_000

    def _patch_now(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(uptimerobot.time, "time", lambda: self.NOW)

    def _responder(self, method: str, data: dict) -> dict:
        start = data["response_times_start_date"]
        return {
            "stat": "ok",
            "pagination": {"offset": 0, "limit": 50, "total": 1},
            "monitors": [{"id": 7, "response_times": [{"datetime": start + 10, "value": 123}]}],
        }

    def test_walks_seven_day_windows_from_watermark(self, monkeypatch: Any) -> None:
        self._patch_now(monkeypatch)
        watermark = self.NOW - 10 * _DAY
        requests_made = _patch_post(monkeypatch, self._responder)

        rows = _collect(
            _FakeResumableManager(),
            "response_times",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        windows = [(r["response_times_start_date"], r["response_times_end_date"]) for r in requests_made]
        assert windows == [
            (watermark, watermark + 7 * _DAY),
            (watermark + 7 * _DAY, self.NOW),
        ]
        assert rows == [
            {"datetime": watermark + 10, "value": 123, "monitor_id": 7},
            {"datetime": watermark + 7 * _DAY + 10, "value": 123, "monitor_id": 7},
        ]

    def test_first_sync_starts_at_initial_lookback(self, monkeypatch: Any) -> None:
        self._patch_now(monkeypatch)
        requests_made = _patch_post(monkeypatch, self._responder)

        _collect(_FakeResumableManager(), "response_times")

        expected_start = self.NOW - RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS * _DAY
        assert requests_made[0]["response_times_start_date"] == expected_start
        assert requests_made[0]["response_times"] == 1

    def test_saves_window_state_between_windows(self, monkeypatch: Any) -> None:
        self._patch_now(monkeypatch)
        watermark = self.NOW - 10 * _DAY
        _patch_post(monkeypatch, self._responder)
        manager = _FakeResumableManager()

        _collect(
            manager,
            "response_times",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert UptimeRobotResumeConfig(offset=0, window_start=watermark + 7 * _DAY) in manager.saved

    def test_resumes_from_saved_window(self, monkeypatch: Any) -> None:
        self._patch_now(monkeypatch)
        watermark = self.NOW - 10 * _DAY
        resume_window = watermark + 7 * _DAY
        requests_made = _patch_post(monkeypatch, self._responder)

        _collect(
            _FakeResumableManager(UptimeRobotResumeConfig(offset=0, window_start=resume_window)),
            "response_times",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        # The completed first window is not re-fetched.
        assert requests_made[0]["response_times_start_date"] == resume_window

    def test_rows_at_or_before_watermark_are_dropped(self, monkeypatch: Any) -> None:
        self._patch_now(monkeypatch)
        watermark = self.NOW - _DAY

        def responder(method: str, data: dict) -> dict:
            return {
                "stat": "ok",
                "pagination": {"offset": 0, "limit": 50, "total": 1},
                "monitors": [
                    {
                        "id": 7,
                        "response_times": [
                            {"datetime": watermark, "value": 1},
                            {"datetime": watermark + 5, "value": 2},
                        ],
                    }
                ],
            }

        _patch_post(monkeypatch, responder)
        rows = _collect(
            _FakeResumableManager(),
            "response_times",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert rows == [{"datetime": watermark + 5, "value": 2, "monitor_id": 7}]


class TestSourceResponseWiring:
    @parameterized.expand(
        [
            ("monitors", ["id"], "asc"),
            ("monitor_logs", ["monitor_id", "datetime", "type"], "desc"),
            ("response_times", ["monitor_id", "datetime"], "desc"),
            ("alert_contacts", ["id"], "asc"),
            ("maintenance_windows", ["id"], "asc"),
            ("status_pages", ["id"], "asc"),
        ]
    )
    def test_primary_keys_and_sort_mode(self, endpoint: str, primary_keys: list[str], sort_mode: str) -> None:
        response = uptimerobot_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # Fan-out endpoints must defer the incremental watermark to job end ("desc"): batches
        # aggregate across monitor pages and time windows, so per-batch maxima aren't safe.
        assert response.sort_mode == sort_mode

    def test_every_declared_endpoint_builds_a_response(self) -> None:
        for endpoint in UPTIMEROBOT_ENDPOINTS:
            response = uptimerobot_source(
                api_key="key",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=MagicMock(),
            )
            config = UPTIMEROBOT_ENDPOINTS[endpoint]
            if config.partition_key:
                assert response.partition_mode == "datetime"
                assert response.partition_keys == [config.partition_key]
            else:
                assert response.partition_mode is None
