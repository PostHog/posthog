import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.clockify import (
    CLOCKIFY_BASE_URL,
    ClockifyPageNumberPaginator,
    ClockifyResumeConfig,
    _chained_resource,
    _clamp_future_value_to_now,
    _flatten_approval_request,
    _flatten_time_entry,
    _format_datetime_z,
    clockify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import CLOCKIFY_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the clockify module.
CLOCKIFY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.clockify.clockify.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ClockifyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session; capture each request's (url, params) AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each request
    is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _wire_bodies(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, str, dict[str, Any]]]:
    """Like ``_wire``, but snapshots the method and JSON body instead of the query params."""
    session.headers = {}
    snapshots: list[tuple[str, str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, request.method, dict(request.json or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return clockify_source(
        api_key="key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


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

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_datetime_z(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


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


class TestFlattenTimeEntry:
    def test_flattens_time_interval(self) -> None:
        row = _flatten_time_entry(
            {
                "id": "T1",
                "timeInterval": {"start": "2026-03-04T00:00:00Z", "end": "2026-03-04T01:00:00Z", "duration": "PT1H"},
            }
        )
        assert row["time_interval_start"] == "2026-03-04T00:00:00Z"
        assert row["time_interval_end"] == "2026-03-04T01:00:00Z"
        assert row["time_interval_duration"] == "PT1H"

    def test_missing_time_interval_is_noop(self) -> None:
        row = _flatten_time_entry({"id": "T1"})
        assert "time_interval_start" not in row


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

    def test_partial_request_only_flattens_what_is_present(self) -> None:
        row = _flatten_approval_request({"approvalRequest": {"id": "AR1"}})
        assert row["approval_request_id"] == "AR1"
        assert "approval_request_state" not in row

    def test_missing_request_is_noop(self) -> None:
        assert _flatten_approval_request({"trackedTime": "PT1H"}) == {"trackedTime": "PT1H"}


class TestPaginator:
    def _paginator(self) -> ClockifyPageNumberPaginator:
        paginator = ClockifyPageNumberPaginator(page_size=2)
        request = mock.MagicMock()
        request.params = {}
        paginator.init_request(request)
        assert request.params == {"page": 1}
        return paginator

    def test_full_page_advances_to_next_page(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response([{"id": "a"}, {"id": "b"}]), [{"id": "a"}, {"id": "b"}])
        assert paginator.has_next_page is True
        request = mock.MagicMock()
        request.params = {}
        paginator.update_request(request)
        assert request.params == {"page": 2}

    def test_short_page_terminates(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response([{"id": "a"}]), [{"id": "a"}])
        assert paginator.has_next_page is False

    def test_empty_page_terminates(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response([]), [])
        assert paginator.has_next_page is False


class TestWorkspacesEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_top_level_pagination_and_no_fan_out(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "W1", "name": "A"}, {"id": "W2"}])])

        rows = _rows(_source("workspaces", _make_manager()))

        assert [r["id"] for r in rows] == ["W1", "W2"]
        # Workspaces is its own endpoint — one request, and it must NOT fan out over workspaces.
        assert len(snapshots) == 1
        assert snapshots[0][0] == f"{CLOCKIFY_BASE_URL}/workspaces"
        assert snapshots[0][1] == {"page": 1, "page-size": 1000}


class TestSingleLevelFanOut:
    def _responses(self) -> list[Response]:
        return [
            _response([{"id": "W1"}, {"id": "W2"}]),
            _response([{"id": "C1", "name": "Acme"}]),
            _response([{"id": "C2"}]),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_workspaces_and_injects_workspace_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, self._responses())

        rows = _rows(_source("clients", _make_manager()))

        assert [(r["id"], r["workspace_id"]) for r in rows] == [("C1", "W1"), ("C2", "W2")]
        assert [url for url, _ in snapshots] == [
            f"{CLOCKIFY_BASE_URL}/workspaces",
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/clients",
            f"{CLOCKIFY_BASE_URL}/workspaces/W2/clients",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_workspace(self, MockSession) -> None:
        session = MockSession.return_value
        # W1 already fully synced last run — only workspaces (re-enumerated) and W2 are fetched.
        snapshots = _wire(session, [_response([{"id": "W1"}, {"id": "W2"}]), _response([{"id": "C2"}])])
        resume = ClockifyResumeConfig(
            fanout_state={"completed": [f"/workspaces/W1/clients"], "current": None, "child_state": None}
        )

        rows = _rows(_source("clients", _make_manager(resume)))

        assert [r["id"] for r in rows] == ["C2"]
        assert [url for url, _ in snapshots] == [
            f"{CLOCKIFY_BASE_URL}/workspaces",
            f"{CLOCKIFY_BASE_URL}/workspaces/W2/clients",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_restarts_from_beginning(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, self._responses())
        # An old-format saved state (no fanout_state) parses but resumes nothing — a full re-read the
        # merge dedupes, rather than mis-mapping the old positional scope onto the new fan-out state.
        rows = _rows(_source("clients", _make_manager(ClockifyResumeConfig(workspace_id="GONE"))))

        assert [r["id"] for r in rows] == ["C1", "C2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_records_completed_child_path(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "W1"}]), _response([{"id": "C1"}])])
        manager = _make_manager()

        _rows(_source("clients", manager))

        assert manager.save_state.called
        last_saved = manager.save_state.call_args.args[0]
        assert isinstance(last_saved, ClockifyResumeConfig)
        assert last_saved.fanout_state is not None
        assert last_saved.fanout_state["completed"] == [f"/workspaces/W1/clients"]


class TestTwoLevelFanOutTasks:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_workspace_then_project_and_injects_both_ids(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "W1"}]),
                _response([{"id": "P1"}, {"id": "P2"}]),
                _response([{"id": "TK1"}]),
                _response([{"id": "TK2"}]),
            ],
        )

        rows = _rows(_source("tasks", _make_manager()))

        assert rows == [
            {"id": "TK1", "workspace_id": "W1", "project_id": "P1"},
            {"id": "TK2", "workspace_id": "W1", "project_id": "P2"},
        ]
        assert [url for url, _ in snapshots] == [
            f"{CLOCKIFY_BASE_URL}/workspaces",
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/projects",
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/projects/P1/tasks",
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/projects/P2/tasks",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_chained_fan_out_disables_resume(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "W1"}]), _response([{"id": "P1"}]), _response([{"id": "TK1"}])])
        manager = _make_manager()

        _rows(_source("tasks", manager))

        # Two dependent resources -> the framework disables resume so a shared hook can't corrupt state.
        manager.save_state.assert_not_called()


class TestTwoLevelFanOutTimeEntries:
    def _base_responses(self, entries: list[dict[str, Any]]) -> list[Response]:
        return [_response([{"id": "W1"}]), _response([{"id": "U1"}]), _response(entries)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_interval_and_injects_workspace_and_user(self, MockSession) -> None:
        session = MockSession.return_value
        entry = {"id": "TE1", "timeInterval": {"start": "2026-03-04T00:00:00Z", "end": None, "duration": None}}
        snapshots = _wire(session, self._base_responses([entry]))

        rows = _rows(_source("time_entries", _make_manager()))

        assert rows[0]["workspace_id"] == "W1"
        assert rows[0]["user_id"] == "U1"
        assert rows[0]["time_interval_start"] == "2026-03-04T00:00:00Z"
        assert snapshots[-1][0] == f"{CLOCKIFY_BASE_URL}/workspaces/W1/user/U1/time-entries"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_passes_start_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, self._base_responses([]))

        _rows(
            _source(
                "time_entries",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        # The server-side `start` filter is only applied to the time-entries request.
        time_entry_params = snapshots[-1][1]
        assert time_entry_params["start"] == "2026-03-04T02:58:14Z"
        # Parent enumeration requests carry no incremental filter.
        assert "start" not in snapshots[0][1]
        assert "start" not in snapshots[1][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_start_filter_on_full_refresh(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, self._base_responses([]))

        _rows(_source("time_entries", _make_manager(), should_use_incremental_field=False))

        assert "start" not in snapshots[-1][1]


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rows_are_read_from_the_envelope(self, endpoint: str, body: Any, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "W1"}]), _response(body)])

        rows = _rows(_source(endpoint, _make_manager()))

        assert rows == [{"id": "E1", "workspace_id": "W1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_null_expense_envelope_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        # Clockify documents all three keys as nullable; a workspace without expense tracking must
        # sync zero rows rather than fail the schema.
        _wire(
            session,
            [_response([{"id": "W1"}]), _response({"dailyTotals": None, "expenses": None, "weeklyTotals": None})],
        )

        assert _rows(_source("expenses", _make_manager())) == []


class TestCustomFieldsEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_no_paging_params_and_stops_after_one_page(self, MockSession) -> None:
        session = MockSession.return_value
        # The endpoint accepts no page/page-size params, so sending them would be noise and a
        # second request would re-read the same collection forever.
        snapshots = _wire(session, [_response([{"id": "W1"}]), _response([{"id": "CF1"}])])

        rows = _rows(_source("custom_fields", _make_manager()))

        assert rows == [{"id": "CF1", "workspace_id": "W1"}]
        assert snapshots[-1] == (f"{CLOCKIFY_BASE_URL}/workspaces/W1/custom-fields", {})


class TestTwoLevelFanOutInvoicePayments:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_workspace_then_invoice_and_injects_both_ids(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "W1"}]),
                _response({"total": 2, "invoices": [{"id": "I1"}, {"id": "I2"}]}),
                _response([{"id": "PM1", "amount": 10}]),
                _response([{"id": "PM2", "amount": 20}]),
            ],
        )

        rows = _rows(_source("invoice_payments", _make_manager()))

        assert rows == [
            {"id": "PM1", "amount": 10, "workspace_id": "W1", "invoice_id": "I1"},
            {"id": "PM2", "amount": 20, "workspace_id": "W1", "invoice_id": "I2"},
        ]
        assert [url for url, _ in snapshots] == [
            f"{CLOCKIFY_BASE_URL}/workspaces",
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/invoices",
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/invoices/I1/payments",
            f"{CLOCKIFY_BASE_URL}/workspaces/W1/invoices/I2/payments",
        ]


class TestTimeOffRequestsEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_posts_the_filter_body_and_reads_the_requests_envelope(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire_bodies(
            session,
            [_response([{"id": "W1"}]), _response({"count": 1, "requests": [{"id": "TO1"}]})],
        )

        rows = _rows(_source("time_off_requests", _make_manager()))

        assert rows == [{"id": "TO1", "workspace_id": "W1"}]
        url, method, body = snapshots[-1]
        assert url == f"{CLOCKIFY_BASE_URL}/workspaces/W1/time-off/requests"
        assert method == "POST"
        # Without an explicit status filter Clockify returns pending requests only.
        assert body == {"page": 1, "pageSize": 200, "statuses": ["ALL"]}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paging_advances_in_the_body(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = {"count": 200, "requests": [{"id": str(i)} for i in range(200)]}
        snapshots = _wire_bodies(
            session,
            [_response([{"id": "W1"}]), _response(full_page), _response({"count": 0, "requests": []})],
        )

        _rows(_source("time_off_requests", _make_manager()))

        assert [body.get("page") for _url, _method, body in snapshots[1:]] == [1, 2]


class TestApprovalRequestsEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_rows_and_pages_on_a_stable_sort(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "W1"}]),
                _response([{"approvalRequest": {"id": "AR1", "owner": {"userId": "U1"}}, "trackedTime": "PT40H"}]),
            ],
        )

        rows = _rows(_source("approval_requests", _make_manager()))

        assert rows[0]["workspace_id"] == "W1"
        assert rows[0]["approval_request_id"] == "AR1"
        assert rows[0]["approval_request_owner_user_id"] == "U1"
        url, params = snapshots[-1]
        assert url == f"{CLOCKIFY_BASE_URL}/workspaces/W1/approval-requests"
        # Approvals are submitted while a sync runs, so an unsorted walk would skip or repeat rows
        # across page boundaries.
        assert params == {"page": 1, "page-size": 1000, "sort-column": "ID", "sort-order": "ASCENDING"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_row_without_an_approval_request_is_dropped(self, MockSession) -> None:
        session = MockSession.return_value
        # Clockify documents the nested request as nullable; such a row has no id, and writing it
        # would seed a null primary key.
        _wire(
            session,
            [
                _response([{"id": "W1"}]),
                _response([{"approvalRequest": None}, {"approvalRequest": {"id": "AR1"}}]),
            ],
        )

        rows = _rows(_source("approval_requests", _make_manager()))

        assert [row["approval_request_id"] for row in rows] == ["AR1"]


class TestUserGroupsEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_keeps_members_and_asks_for_team_managers(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": "W1"}]),
                _response([{"id": "G1", "name": "Design", "userIds": ["U1", "U2"], "teamManagers": [{"id": "U1"}]}]),
            ],
        )

        rows = _rows(_source("user_groups", _make_manager()))

        assert rows[0]["workspace_id"] == "W1"
        assert rows[0]["userIds"] == ["U1", "U2"]
        url, params = snapshots[-1]
        assert url == f"{CLOCKIFY_BASE_URL}/workspaces/W1/user-groups"
        # Team managers are left out of the response unless asked for.
        assert params["includeTeamManagers"] == "true"


class TestChainedResource:
    def test_endpoint_without_a_fan_out_parent_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no fan-out parent"):
            _chained_resource("clients", lambda row: row)


class TestFailLoud:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 body that is not a list means the response shape changed — fail loud, not 0 rows.
        _wire(session, [_response({"error": "unexpected"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("workspaces", _make_manager()))


class TestClockifySourceResponse:
    @parameterized.expand([(name,) for name in CLOCKIFY_ENDPOINTS])
    def test_primary_keys_and_sort_mode_match_config(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        config = CLOCKIFY_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode

    def test_time_entries_is_desc_and_partitioned(self) -> None:
        response = _source("time_entries", _make_manager())
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["time_interval_start"]
        assert response.partition_mode == "datetime"

    def test_full_refresh_endpoint_has_no_partition(self) -> None:
        response = _source("clients", _make_manager())
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestValidateCredentials:
    @pytest.mark.parametrize("status,expected", [(200, True), (401, False), (403, False)])
    def test_status_maps_to_validity(self, status: int, expected: bool) -> None:
        with mock.patch(CLOCKIFY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
            assert validate_credentials("key") is expected

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(CLOCKIFY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False
