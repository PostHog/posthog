import dataclasses
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.signoz import SigNozSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz import signoz as sgz
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.settings import SIGNOZ_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz import (
    SigNozResumeConfig,
    _extract_config_items,
    _extract_raw_rows,
    _to_epoch_ms,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.source import SigNozSource

CONFIG = SigNozSourceConfig(host="example.signoz.io", api_key="key")


class TestToEpochMs:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 1, 1, tzinfo=UTC), 1767225600000),
            (datetime(2026, 1, 1), 1767225600000),  # naive -> UTC
            (date(2026, 1, 1), 1767225600000),
            (1767225600000, 1767225600000),  # already ms
            (1767225600, 1767225600000),  # seconds -> ms
            ("2026-01-01T00:00:00Z", 1767225600000),
            # Go marshals time.Time with nanosecond precision; must still parse.
            ("2026-01-01T00:00:00.123456789Z", 1767225600123),
            ("not-a-timestamp", None),
            (None, None),
        ],
    )
    def test_to_epoch_ms(self, value: Any, expected: int | None) -> None:
        assert _to_epoch_ms(value) == expected


class TestExtractRawRows:
    @pytest.mark.parametrize(
        "response",
        [
            {},
            {"data": {}},
            {"data": {"data": {}}},
            {"data": {"data": {"results": []}}},
            {"data": {"data": {"results": [{"queryName": "A", "rows": None}]}}},
            "unexpected",
            None,
        ],
    )
    def test_malformed_envelope_returns_empty(self, response: Any) -> None:
        assert _extract_raw_rows(response) == []


class TestExtractConfigItems:
    def test_notification_channels_allowlist_strips_credential_data(self) -> None:
        # The `data` field carries receiver secrets (Slack webhook URLs, PagerDuty keys); the
        # allowlist must drop it (and anything else off-list) before it reaches the warehouse.
        response = {
            "status": "success",
            "data": [
                {
                    "id": "c1",
                    "name": "oncall",
                    "type": "slack",
                    "data": {"url": "https://hooks.slack.com/services/SECRET"},
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "internal_field": "drop me",
                }
            ],
        }
        assert _extract_config_items(response, SIGNOZ_ENDPOINTS["notification_channels"]) == [
            {
                "id": "c1",
                "name": "oncall",
                "type": "slack",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-02T00:00:00Z",
            }
        ]

    @pytest.mark.parametrize(
        "response",
        [{}, {"data": None}, {"data": {"rules": "nope"}}, None],
    )
    def test_malformed_response_returns_empty(self, response: Any) -> None:
        assert _extract_config_items(response, SIGNOZ_ENDPOINTS["alert_rules"]) == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "schema_name", "expected_valid"),
        [
            (200, None, True),
            (401, None, False),
            # 403 at source-create is a valid key without the probe's role -> accept.
            (403, None, True),
            # 403 on a scoped probe is a hard failure.
            (403, "logs", False),
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))):
            is_valid, error = validate_credentials("example.signoz.io", "key", schema_name=schema_name)

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_redirect_is_rejected(self) -> None:
        redirect = ScriptedResponse(status=302, headers={"Location": "https://internal.example.com/"})
        with scripted_network(always(redirect)):
            is_valid, error = validate_credentials("example.signoz.io", "key")

        assert is_valid is False
        assert error is not None

    @pytest.mark.parametrize("host", ["", "not a host!", "bad_host/"])
    def test_invalid_host_is_rejected_without_a_request(self, host: str) -> None:
        is_valid, error = validate_credentials(host, "key")
        assert is_valid is False
        assert error == "Invalid SigNoz host"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz._is_host_safe")
    def test_unsafe_host_is_blocked(self, mock_host_safe: mock.MagicMock) -> None:
        mock_host_safe.return_value = (False, "Hosts with internal IP addresses are not allowed")
        is_valid, error = validate_credentials("10.0.0.1", "key", team_id=42)
        assert is_valid is False
        assert error == "Hosts with internal IP addresses are not allowed"


class TestSigNozSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pks", "expected_partition_key"),
        [
            ("logs", ["id"], "timestamp"),
            ("traces", ["trace_id", "span_id"], "timestamp"),
            ("alert_rules", ["id"], "createAt"),
            ("dashboards", ["id"], "createdAt"),
            ("notification_channels", ["id"], "createdAt"),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], expected_partition_key: str) -> None:
        response = SourceDriver(SigNozSource(), CONFIG).run(endpoint, always(ScriptedResponse(json=_page([])))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [expected_partition_key]


def _page(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "success", "data": {"type": "raw", "data": {"results": [{"queryName": "A", "rows": rows}]}}}


def _with_page_size(endpoint: str, page_size: int) -> Any:
    return dataclasses.replace(SIGNOZ_ENDPOINTS[endpoint], page_size=page_size)


def _log_row(ts: str, row_id: str) -> dict[str, Any]:
    return {"timestamp": ts, "data": {"id": row_id, "body": f"line {row_id}"}}


class TestGetRows:
    def _run(
        self,
        endpoint: str,
        responses: list[Any],
        resume_state: SigNozResumeConfig | None = None,
        page_size: int = 2,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> DriveResult:
        with mock.patch.dict(sgz.SIGNOZ_ENDPOINTS, {endpoint: _with_page_size(endpoint, page_size)}):
            return SourceDriver(SigNozSource(), CONFIG).run(
                endpoint,
                [ScriptedResponse(json=response) for response in responses],
                resume_state=resume_state,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )

    def test_notification_channels_endpoint_drops_credential_data(self) -> None:
        # End-to-end guard on the sync path: the receiver `data` payload never reaches the
        # yielded rows, so imported channel secrets can't land in the warehouse table.
        responses = [
            {
                "status": "success",
                "data": [{"id": "c1", "name": "oncall", "type": "slack", "data": {"url": "https://secret"}}],
            }
        ]
        result = self._run("notification_channels", responses)

        assert result.raised is None
        assert result.items == [[{"id": "c1", "name": "oncall", "type": "slack"}]]

    def test_full_page_advances_window_start_and_saves_state_after_yield(self) -> None:
        responses = [
            _page([_log_row("2026-01-01T00:00:00Z", "1"), _log_row("2026-01-01T00:00:01Z", "2")]),
            _page([_log_row("2026-01-01T00:00:02Z", "3")]),
        ]
        result = self._run(
            "logs",
            responses,
            resume_state=SigNozResumeConfig(window_start_ms=1767225600000, window_end_ms=1767312000000, offset=0),
            page_size=2,
        )

        assert result.raised is None
        assert [len(b) for b in result.items] == [2, 1]
        # Window start advanced to the last row's timestamp; one trailing row at that ms is
        # skipped via the offset instead of an ever-growing window offset.
        assert len(result.saved_states) == 1
        assert result.saved_states[0].window_start_ms == 1767225601000
        assert result.saved_states[0].offset == 1
        # The second request starts at the advanced window with the trailing-row offset.
        second_body = result.requests[1].json()
        assert second_body["start"] == 1767225601000
        assert second_body["compositeQuery"]["queries"][0]["spec"]["offset"] == 1

    def test_full_page_within_one_millisecond_grows_offset(self) -> None:
        same_ts = "2026-01-01T00:00:00Z"
        responses = [
            _page([_log_row(same_ts, "1"), _log_row(same_ts, "2")]),
            _page([_log_row(same_ts, "3"), _log_row(same_ts, "4")]),
            _page([]),
        ]
        result = self._run(
            "logs",
            responses,
            resume_state=SigNozResumeConfig(window_start_ms=1767225600000, window_end_ms=1767225700000, offset=0),
            page_size=2,
        )

        # The whole window-start millisecond spans multiple pages: offset accumulates so no
        # rows are skipped and none are refetched.
        assert [s.offset for s in result.saved_states] == [2, 4]
        assert all(s.window_start_ms == 1767225600000 for s in result.saved_states)
        assert [request.json()["compositeQuery"]["queries"][0]["spec"]["offset"] for request in result.requests] == [
            0,
            2,
            4,
        ]

    def test_incremental_watermark_sets_window_start(self) -> None:
        responses = [_page([])]
        result = self._run(
            "logs",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert result.requests[0].json()["start"] == 1767225600000

    def test_first_sync_uses_lookback_window(self) -> None:
        responses = [_page([])]
        result = self._run("logs", responses)

        body = result.requests[0].json()
        lookback_days = (body["end"] - body["start"]) / 1000 / 86400
        assert round(lookback_days) == SIGNOZ_ENDPOINTS["logs"].default_lookback_days
