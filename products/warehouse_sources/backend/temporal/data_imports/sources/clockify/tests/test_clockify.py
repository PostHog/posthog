from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.clockify import (
    ClockifyResumeConfig,
    _chained_resource,
    _clamp_future_value_to_now,
    _flatten_approval_request,
    _format_datetime_z,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import CLOCKIFY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.source import ClockifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clockify import (
    ClockifySourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ClockifySource(), ClockifySourceConfig(api_key="key"))


def _response(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestFormatDatetimeZ:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime_z(value) == expected


class TestClampFutureValueToNow:
    @parameterized.expand(
        [
            ("future_datetime", datetime(2027, 2, 5, tzinfo=UTC), datetime(2026, 6, 15, 12, tzinfo=UTC)),
            ("past_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
            ("non_iso_string_passthrough", "cursor", "cursor"),
            ("future_iso_string", "2030-01-01T00:00:00Z", datetime(2026, 6, 15, 12, tzinfo=UTC)),
            ("past_iso_string", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_clamp(self, _name: str, value: Any, expected: Any) -> None:
        assert _clamp_future_value_to_now(value) == expected


class TestFlattenApprovalRequest:
    def test_flattens_the_nested_request(self) -> None:
        row = _flatten_approval_request(
            {
                "approvalRequest": {
                    "id": "AR1",
                    "status": {"state": "APPROVED", "note": ""},
                    "owner": {"userId": "U1", "userName": "Ada"},
                    "dateRange": {"start": "2026-03-02T00:00:00Z", "end": "2026-03-08T23:59:59Z"},
                },
                "trackedTime": "PT40H",
            }
        )
        assert row["approval_request_id"] == "AR1"
        assert row["approval_request_state"] == "APPROVED"
        assert row["approval_request_owner_user_id"] == "U1"
        assert row["approval_request_start"] == "2026-03-02T00:00:00Z"
        assert row["approval_request_end"] == "2026-03-08T23:59:59Z"

    def test_missing_request_is_noop(self) -> None:
        assert _flatten_approval_request({"trackedTime": "PT1H"}) == {"trackedTime": "PT1H"}


class TestSingleLevelFanOut:
    def _responses(self) -> list[ScriptedResponse]:
        return [
            _response([{"id": "W1"}, {"id": "W2"}]),
            _response([{"id": "C1", "name": "Acme"}]),
            _response([{"id": "C2"}]),
        ]

    def test_fans_out_over_workspaces_and_injects_workspace_id(self) -> None:
        result = _driver().run("clients", self._responses())

        assert result.raised is None
        assert [(r["id"], r["workspace_id"]) for r in result.rows] == [("C1", "W1"), ("C2", "W2")]
        assert result.paths == [
            "/api/v1/workspaces",
            "/api/v1/workspaces/W1/clients",
            "/api/v1/workspaces/W2/clients",
        ]

    def test_resume_skips_completed_workspace(self) -> None:
        # W1 already fully synced last run — only workspaces (re-enumerated) and W2 are fetched.
        resume = ClockifyResumeConfig(
            fanout_state={"completed": [f"/workspaces/W1/clients"], "current": None, "child_state": None}
        )

        result = _driver().run(
            "clients", [_response([{"id": "W1"}, {"id": "W2"}]), _response([{"id": "C2"}])], resume_state=resume
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["C2"]
        assert result.paths == [
            "/api/v1/workspaces",
            "/api/v1/workspaces/W2/clients",
        ]


class TestTwoLevelFanOutTasks:
    def test_fans_out_workspace_then_project_and_injects_both_ids(self) -> None:
        result = _driver().run(
            "tasks",
            [
                _response([{"id": "W1"}]),
                _response([{"id": "P1"}, {"id": "P2"}]),
                _response([{"id": "TK1"}]),
                _response([{"id": "TK2"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "TK1", "workspace_id": "W1", "project_id": "P1"},
            {"id": "TK2", "workspace_id": "W1", "project_id": "P2"},
        ]
        assert result.paths == [
            "/api/v1/workspaces",
            "/api/v1/workspaces/W1/projects",
            "/api/v1/workspaces/W1/projects/P1/tasks",
            "/api/v1/workspaces/W1/projects/P2/tasks",
        ]


class TestTwoLevelFanOutTimeEntries:
    def _base_responses(self, entries: list[dict[str, Any]]) -> list[ScriptedResponse]:
        return [_response([{"id": "W1"}]), _response([{"id": "U1"}]), _response(entries)]

    def test_flattens_interval_and_injects_workspace_and_user(self) -> None:
        entry = {"id": "TE1", "timeInterval": {"start": "2026-03-04T00:00:00Z", "end": None, "duration": None}}
        result = _driver().run("time_entries", self._base_responses([entry]))

        assert result.raised is None
        assert result.rows[0]["workspace_id"] == "W1"
        assert result.rows[0]["user_id"] == "U1"
        assert result.rows[0]["time_interval_start"] == "2026-03-04T00:00:00Z"
        assert result.paths[-1] == "/api/v1/workspaces/W1/user/U1/time-entries"

    def test_incremental_passes_start_filter(self) -> None:
        result = _driver().run(
            "time_entries",
            self._base_responses([]),
            incremental_field="time_interval_start",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        # The server-side `start` filter is only applied to the time-entries request.
        assert result.requests[-1].param("start") == "2026-03-04T02:58:14Z"
        # Parent enumeration requests carry no incremental filter.
        assert result.requests[0].param("start") is None
        assert result.requests[1].param("start") is None


class TestEnvelopedEndpoints:
    """Endpoints whose rows sit inside a response envelope rather than a bare array."""

    @parameterized.expand(
        [
            (
                "expenses",
                {"dailyTotals": None, "weeklyTotals": None, "expenses": {"count": 1, "expenses": [{"id": "E1"}]}},
            ),
            ("expense_categories", {"count": 1, "categories": [{"id": "E1"}]}),
            ("invoices", {"total": 1, "invoices": [{"id": "E1"}]}),
        ]
    )
    def test_rows_are_read_from_the_envelope(self, endpoint: str, body: Any) -> None:
        result = _driver().run(endpoint, [_response([{"id": "W1"}]), _response(body)])

        assert result.raised is None
        assert result.rows == [{"id": "E1", "workspace_id": "W1"}]


class TestTwoLevelFanOutInvoicePayments:
    def test_fans_out_workspace_then_invoice_and_injects_both_ids(self) -> None:
        result = _driver().run(
            "invoice_payments",
            [
                _response([{"id": "W1"}]),
                _response({"total": 2, "invoices": [{"id": "I1"}, {"id": "I2"}]}),
                _response([{"id": "PM1", "amount": 10}]),
                _response([{"id": "PM2", "amount": 20}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "PM1", "amount": 10, "workspace_id": "W1", "invoice_id": "I1"},
            {"id": "PM2", "amount": 20, "workspace_id": "W1", "invoice_id": "I2"},
        ]
        assert result.paths == [
            "/api/v1/workspaces",
            "/api/v1/workspaces/W1/invoices",
            "/api/v1/workspaces/W1/invoices/I1/payments",
            "/api/v1/workspaces/W1/invoices/I2/payments",
        ]


class TestTimeOffRequestsEndpoint:
    def test_paging_advances_in_the_body(self) -> None:
        full_page = {"count": 200, "requests": [{"id": str(i)} for i in range(200)]}
        result = _driver().run(
            "time_off_requests",
            [_response([{"id": "W1"}]), _response(full_page), _response({"count": 0, "requests": []})],
        )

        assert result.raised is None
        assert [request.json().get("page") for request in result.requests[1:]] == [1, 2]


class TestApprovalRequestsEndpoint:
    def test_row_without_an_approval_request_is_dropped(self) -> None:
        # Clockify documents the nested request as nullable; such a row has no id, and writing it
        # would seed a null primary key.
        result = _driver().run(
            "approval_requests",
            [
                _response([{"id": "W1"}]),
                _response([{"approvalRequest": None}, {"approvalRequest": {"id": "AR1"}}]),
            ],
        )

        assert result.raised is None
        assert [row["approval_request_id"] for row in result.rows] == ["AR1"]


class TestChainedResource:
    def test_endpoint_without_a_fan_out_parent_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no fan-out parent"):
            _chained_resource("clients", lambda row: row)


class TestFailLoud:
    def test_non_list_body_raises(self) -> None:
        # A 200 body that is not a list means the response shape changed — fail loud, not 0 rows.
        result = _driver().run("workspaces", [_response({"error": "unexpected"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestClockifySourceResponse:
    @parameterized.expand([(name,) for name in CLOCKIFY_ENDPOINTS])
    def test_primary_keys_and_sort_mode_match_config(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [])
        response = result.response
        config = CLOCKIFY_ENDPOINTS[endpoint]
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
