import json
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.automox import automox
from products.warehouse_sources.sources.automox._config import AutomoxSourceConfig
from products.warehouse_sources.sources.automox.automox import (
    MULTIPLE_ORGS_ERROR,
    ORG_NOT_FOUND_ERROR,
    AutomoxOrganizationError,
    AutomoxResumeConfig,
    AutomoxRetryableError,
    _flatten_device_inventory,
    _incremental_param_value,
    _shape_audit_event,
    resolve_organization,
    validate_credentials,
)
from products.warehouse_sources.sources.automox.settings import AUTOMOX_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.sources.automox.source import AutomoxSource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)

ORGS_BODY = [
    {"id": 123, "uuid": "uuid-123", "name": "Org A"},
    {"id": 456, "uuid": "uuid-456", "name": "Org B"},
]


def _response_with_status(status_code: int, body: Any = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = b"" if body is None else json.dumps(body).encode()
    return response


def _driver(organization_id: str | None = "123") -> SourceDriver:
    return SourceDriver(AutomoxSource(), AutomoxSourceConfig(api_key="key", organization_id=organization_id))


class TestFetchJson:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        # No-op the backoff sleep so the 5 attempts run instantly.
        with patch.object(automox._fetch_json.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(AutomoxRetryableError):
                automox._fetch_json(session, "https://console.automox.com/api/servers", MagicMock())
        assert session.get.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        with pytest.raises(requests.HTTPError):
            automox._fetch_json(session, "https://console.automox.com/api/servers", MagicMock())


class TestFetchPage:
    @parameterized.expand(
        [
            ("bare_endpoint_object_body", "devices", {"error": "unexpected"}),
            ("wrapped_endpoint_list_body", "policy_runs", [{"policy_id": 1}]),
        ]
    )
    def test_contract_violations_raise_value_error(self, _name: str, endpoint: str, body: Any) -> None:
        # A malformed 200 is a permanent contract violation, so it must bypass the retry decorator.
        session = MagicMock()
        session.get.return_value = _response_with_status(200, body)
        with pytest.raises(ValueError):
            automox._fetch_page(session, AUTOMOX_ENDPOINTS[endpoint], "https://console.automox.com/api/x", MagicMock())
        assert session.get.call_count == 1


class TestIncrementalParamValue:
    @parameterized.expand(
        [
            # policy_runs subtracts the 24h lookback and formats a full RFC3339 timestamp.
            (
                "policy_runs_datetime",
                "policy_runs",
                datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
                "2026-03-09T12:00:00Z",
            ),
            ("policy_runs_string", "policy_runs", "2026-03-10T12:00:00Z", "2026-03-09T12:00:00Z"),
            # events subtracts a 1-day lookback and formats a date-only value.
            ("events_datetime", "events", datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC), "2026-03-09"),
            ("events_string", "events", "2026-03-10T12:00:00Z", "2026-03-09"),
        ]
    )
    def test_formats_watermark(self, _name: str, endpoint: str, last_value: Any, expected: str) -> None:
        assert _incremental_param_value(AUTOMOX_ENDPOINTS[endpoint], last_value) == expected

    @parameterized.expand([("none", None), ("garbage_string", "not-a-date")])
    def test_unusable_watermark_returns_none(self, _name: str, last_value: Any) -> None:
        assert _incremental_param_value(AUTOMOX_ENDPOINTS["policy_runs"], last_value) is None

    def test_future_watermark_is_clamped_to_now(self) -> None:
        # A future-dated cursor must not produce a filter past now, which would skip new rows forever.
        value = _incremental_param_value(AUTOMOX_ENDPOINTS["policy_runs"], datetime(2099, 1, 1, tzinfo=UTC))
        assert value is not None
        assert datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) <= datetime.now(UTC)


class TestResolveOrganization:
    @parameterized.expand(
        [
            ("explicit_id", "456", (456, "uuid-456")),
            ("explicit_id_with_whitespace", " 123 ", (123, "uuid-123")),
        ]
    )
    def test_explicit_id_is_matched(self, _name: str, organization_id: str, expected: tuple[int, str]) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200, ORGS_BODY)
        assert resolve_organization(session, organization_id, MagicMock()) == expected

    @parameterized.expand(
        [
            ("unknown_id", "999", ORG_NOT_FOUND_ERROR),
            ("multiple_orgs_no_id", None, MULTIPLE_ORGS_ERROR),
        ]
    )
    def test_unresolvable_org_raises(self, _name: str, organization_id: str | None, expected_prefix: str) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200, ORGS_BODY)
        with pytest.raises(AutomoxOrganizationError, match=expected_prefix):
            resolve_organization(session, organization_id, MagicMock())


class TestMakeSession:
    def test_disables_sample_capture_and_redacts_key(self) -> None:
        # `/orgs` and `/users` responses carry org `access_key` secrets the name-based sample
        # scrubbers don't recognise, so the session must opt out of HTTP sample capture and mask
        # the bearer token in logged URLs.
        with scripted_network([]) as network:
            automox._make_session("secret-key")
        kwargs = network.session_options[0]
        assert kwargs["capture"] is False
        assert kwargs["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    def test_valid_key_single_org(self) -> None:
        with scripted_network([ScriptedResponse(json=[ORGS_BODY[0]])]) as network:
            assert validate_credentials("key") == (True, None)
        assert network.requests_log[0].path == "/api/orgs"

    def test_invalid_key_returns_friendly_error(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            ok, error = validate_credentials("bad-key")
        assert ok is False
        assert error is not None
        assert "API key" in error
        assert network.requests_log[0].headers["authorization"] == "Bearer bad-key"

    def test_multiple_orgs_without_id_returns_org_error(self) -> None:
        with scripted_network([ScriptedResponse(json=ORGS_BODY)]) as network:
            ok, error = validate_credentials("key")
        assert ok is False
        assert error is not None
        assert MULTIPLE_ORGS_ERROR in error
        assert network.requests_log[0].path == "/api/orgs"


class TestGetRows:
    def test_paginates_until_short_page_and_saves_state_after_yield(self) -> None:
        page_size = AUTOMOX_ENDPOINTS["devices"].page_size
        full_page = [{"id": i} for i in range(page_size)]
        last_page = [{"id": page_size}]
        result = _driver().run(
            "devices",
            [ScriptedResponse(json=ORGS_BODY), ScriptedResponse(json=full_page), ScriptedResponse(json=last_page)],
        )

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        # One org-resolution call plus two pages.
        assert result.paths == ["/api/orgs", "/api/servers", "/api/servers"]
        assert result.params("page")[1:] == ["0", "1"]
        # The `o` org param rides on every page request.
        assert result.params("o")[1:] == ["123", "123"]
        # State points at the next page and is only saved after a full (non-terminal) page.
        assert result.saved_states == [AutomoxResumeConfig(page=1, incremental_param_value=None)]
        assert result.committed_states == [AutomoxResumeConfig(page=1, incremental_param_value=None)]

    def test_resume_seeds_page_and_reuses_stored_incremental_value(self) -> None:
        # On resume the original run's time filter must be reused verbatim: recomputing it from the
        # advanced watermark would change the filtered result set under the saved page number.
        result = _driver().run(
            "policy_runs",
            [ScriptedResponse(json=ORGS_BODY), ScriptedResponse(json={"data": [{"execution_token": "b"}]})],
            resume_state=AutomoxResumeConfig(page=1, incremental_param_value="2026-01-01T00:00:00Z"),
            incremental_field="run_time",
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.paths == ["/api/orgs", "/api/policy-history/policy-runs"]
        assert result.params("page")[1:] == ["1"]
        assert result.params("start_time")[1:] == ["2026-01-01T00:00:00Z"]

    def test_policy_runs_sends_org_uuid_sort_and_start_time(self) -> None:
        result = _driver().run(
            "policy_runs",
            [ScriptedResponse(json=ORGS_BODY), ScriptedResponse(json={"data": [{"execution_token": "a"}]})],
            incremental_field="run_time",
            db_incremental_field_last_value=datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.paths == ["/api/orgs", "/api/policy-history/policy-runs"]
        assert result.params("org")[1:] == ["uuid-123"]
        assert result.params("sort")[1:] == ["run_time:asc"]
        # 24h lookback applied to the watermark.
        assert result.params("start_time")[1:] == ["2026-03-09T12:00:00Z"]

    def test_organizations_endpoint_restricts_to_configured_org(self) -> None:
        # `/orgs` lists every organization the API key can access, but the table must expose only
        # the org this source is configured for — otherwise a teammate could read metadata for
        # organizations the source owner never selected.
        result = _driver("456").run(
            "organizations", [ScriptedResponse(json=ORGS_BODY), ScriptedResponse(json=ORGS_BODY)]
        )
        assert result.raised is None
        assert result.rows == [ORGS_BODY[1]]

    def test_credential_fields_are_stripped_from_rows(self) -> None:
        # Automox embeds an org enrollment `access_key` at the top level and again under nested
        # `orgs[]` entries, plus an `intercom_hmac` identity token on user rows; none may reach the
        # warehouse, at any depth.
        user_row = {
            "id": 7,
            "access_key": "org-enrollment-secret",
            "intercom_hmac": "identity-token",
            "orgs": [{"id": 123, "access_key": "nested-secret", "name": "Org A"}],
        }
        result = _driver().run("users", [ScriptedResponse(json=ORGS_BODY), ScriptedResponse(json=[user_row])])
        assert result.raised is None
        assert result.rows == [{"id": 7, "orgs": [{"id": 123, "name": "Org A"}]}]

    def test_missing_org_uuid_raises_for_policy_runs(self) -> None:
        result = _driver().run("policy_runs", [ScriptedResponse(json=[{"id": 123, "name": "Org A"}])])
        assert isinstance(result.raised, AutomoxOrganizationError)
        assert ORG_NOT_FOUND_ERROR in str(result.raised)


def _inventory_reading(name: str, value: Any, reading_type: str = "string") -> dict[str, Any]:
    return {
        "name": name,
        "friendly_name": name.replace("_", " ").title(),
        "description": f"{name} reading",
        "collected_at": "2026-02-13T19:33:40+00:00",
        "type": reading_type,
        "value": value,
        "tags": ["system"],
    }


INVENTORY_BODY = {
    "categories": {
        "Hardware": {
            "sub_categories": {
                "Hardware": {"data": [_inventory_reading("board_serial", "SN-1")]},
                "CPU": {"data": [_inventory_reading("cpu_info", [{"model": "amd64"}], "data_records")]},
            }
        }
    }
}


class TestFlattenDeviceInventory:
    def test_accepts_the_documented_nested_categories_level(self) -> None:
        # The API reference nests a second `Categories` level that the example responses omit.
        payload = {"categories": {"Categories": INVENTORY_BODY["categories"]}}
        assert len(_flatten_device_inventory(payload)) == 2

    @parameterized.expand(
        [
            ("empty_body", {}),
            ("null_categories", {"categories": None}),
            ("category_without_sub_categories", {"categories": {"Hardware": {}}}),
            ("sub_category_without_data", {"categories": {"Hardware": {"sub_categories": {"CPU": {}}}}}),
            (
                "reading_without_name",
                {"categories": {"Hardware": {"sub_categories": {"CPU": {"data": [{"value": "x"}]}}}}},
            ),
        ]
    )
    def test_unusable_payloads_yield_no_rows(self, _name: str, payload: Any) -> None:
        # Automox varies which categories a device reports by OS and by the customer's tier, so an
        # absent branch must be skipped rather than crash the sync.
        assert _flatten_device_inventory(payload) == []


class TestFanOutAndUnpaginatedEndpoints:
    @staticmethod
    def _inventory_routes(*device_uuids: str) -> dict[str, list[ScriptedResponse]]:
        routes = {
            "/api/orgs": [ScriptedResponse(json=ORGS_BODY)],
            "/api/servers": [
                ScriptedResponse(json=[{"id": index, "uuid": uuid} for index, uuid in enumerate(device_uuids, start=1)])
            ],
        }
        for uuid in device_uuids:
            routes[f"/api/device-details/orgs/uuid-123/devices/{uuid}/inventory"] = [
                ScriptedResponse(json=INVENTORY_BODY)
            ]
        return routes

    def test_device_inventory_calls_each_device_and_injects_parent_columns(self) -> None:
        # Readings aggregate across every device, so each row needs the device identifiers: they
        # join the table back to devices and complete the primary key.
        result = _driver().run("device_inventory", route(self._inventory_routes("dev-1", "dev-2")))

        assert result.raised is None
        assert [path for path in result.paths if "/inventory" in path] == [
            "/api/device-details/orgs/uuid-123/devices/dev-1/inventory",
            "/api/device-details/orgs/uuid-123/devices/dev-2/inventory",
        ]
        assert len(result.rows) == 4
        assert {(r["device_uuid"], r["device_id"]) for r in result.rows} == {("dev-1", 1), ("dev-2", 2)}

    def test_device_inventory_requires_an_org_uuid(self) -> None:
        result = _driver().run("device_inventory", [ScriptedResponse(json=[{"id": 123, "name": "Org A"}])])
        assert isinstance(result.raised, AutomoxOrganizationError)
        assert ORG_NOT_FOUND_ERROR in str(result.raised)

    def test_fan_out_resume_skips_parents_already_walked(self) -> None:
        result = _driver().run(
            "device_inventory",
            route(self._inventory_routes("dev-1", "dev-2")),
            resume_state=AutomoxResumeConfig(page=0, parent_page=0, parent_index=1),
        )
        assert result.raised is None
        assert [path for path in result.paths if "/inventory" in path] == [
            "/api/device-details/orgs/uuid-123/devices/dev-2/inventory"
        ]
        assert {r["device_uuid"] for r in result.rows} == {"dev-2"}

    def test_remediation_issues_paginate_per_action_set(self) -> None:
        page_size = AUTOMOX_ENDPOINTS["remediation_issues"].page_size
        full_page = {"data": [{"id": i, "issue_type": "unknown-host"} for i in range(page_size)]}
        last_page = {"data": [{"id": page_size, "issue_type": "unknown-host"}]}
        result = _driver().run(
            "remediation_issues",
            route(
                {
                    "/api/orgs": [ScriptedResponse(json=ORGS_BODY)],
                    "/api/orgs/123/remediations/action-sets": [ScriptedResponse(json={"data": [{"id": 17194}]})],
                    "/api/orgs/123/remediations/action-sets/17194/issues": [
                        ScriptedResponse(json=full_page),
                        ScriptedResponse(json=last_page),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [request.param("page") for request in result.requests if request.path.endswith("/issues")] == [
            "0",
            "1",
        ]
        assert len(result.rows) == page_size + 1
        # The issue id is only unique within its action set, so the action set id completes the key.
        assert all(row["action_set_id"] == 17194 for row in result.rows)
        # Mid-parent state points at the next child page, then advances past the finished parent.
        assert result.saved_states == [
            AutomoxResumeConfig(page=1, parent_page=0, parent_index=0),
            AutomoxResumeConfig(page=0, parent_page=0, parent_index=1),
        ]


def _report_body(endpoint: str, device_ids: list[int]) -> dict[str, Any]:
    section = "nonCompliant" if endpoint == "needs_attention_devices" else "prepatch"
    return {section: {"total": len(device_ids), "devices": [{"id": i, "name": f"host-{i}"} for i in device_ids]}}


class TestReportEndpoints:
    @parameterized.expand([("needs_attention_devices",), ("prepatch_devices",)])
    def test_pages_by_offset_until_an_empty_page(self, endpoint: str) -> None:
        # A short page does not end the walk: `limit` may count nested patches rather than devices.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=ORGS_BODY),
                ScriptedResponse(json=_report_body(endpoint, [1, 2])),
                ScriptedResponse(json=_report_body(endpoint, [3])),
                ScriptedResponse(json=_report_body(endpoint, [])),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.params("offset")[1:] == ["0", "250", "500"]
        assert result.params("o")[1:] == ["123", "123", "123"]
        assert result.params("page")[1:] == [None, None, None]

    @parameterized.expand(
        [
            ("report_object", {"nonCompliant": {"devices": [{"id": 1}]}}, [{"id": 1}]),
            ("array_of_reports", [{"nonCompliant": {"devices": [{"id": 1}]}}], [{"id": 1}]),
            ("no_section", {"total": 0}, []),
            ("null_devices", {"nonCompliant": {"devices": None}}, []),
        ]
    )
    def test_accepts_both_documented_report_shapes(self, _name: str, body: Any, expected: list[Any]) -> None:
        responses = [ScriptedResponse(json=ORGS_BODY), ScriptedResponse(json=body)]
        if expected:
            responses.append(ScriptedResponse(json=[]))
        result = _driver().run("needs_attention_devices", responses)
        assert result.raised is None
        assert result.rows == expected

    def test_stops_when_the_server_ignores_the_offset(self) -> None:
        # Offset paging only ends on an empty page; a repeated page must not loop forever.
        page = _report_body("prepatch_devices", [1, 2])
        result = _driver().run(
            "prepatch_devices",
            [ScriptedResponse(json=ORGS_BODY), ScriptedResponse(json=page), ScriptedResponse(json=page)],
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]


AUDIT_PATH = "/api/audit-service/v1/orgs/uuid-123/events"
AUDIT_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _audit_event(event_id: str, time: Any = 1774432800.123456, **extra: Any) -> dict[str, Any]:
    return {"_id": event_id, "time": time, "message": "User Created", "metadata": {"uid": f"uid-{event_id}"}, **extra}


def _audit_page(events: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    metadata: dict[str, Any] = {"count": len(events), "ocsf_version": "1.1.0"}
    if next_cursor is not None:
        metadata["next"] = f"https://console.automox.com/api{AUDIT_PATH[4:]}?cursor={next_cursor}&limit=1000"
    return ScriptedResponse(json={"metadata": metadata, "data": events})


def _audit_requests(result: Any) -> list[RecordedRequest]:
    return [request for request in result.requests if request.path == AUDIT_PATH]


class TestAuditEvents:
    @time_machine.travel(AUDIT_NOW, tick=False)
    def test_walks_windows_oldest_first_and_follows_the_cursor(self) -> None:
        result = _driver().run(
            "audit_events",
            [
                ScriptedResponse(json=ORGS_BODY),
                _audit_page([_audit_event("a"), _audit_event("b")], next_cursor="b"),
                _audit_page([_audit_event("c")]),
                _audit_page([]),
            ],
            incremental_field="event_time",
            db_incremental_field_last_value=datetime(2026, 4, 20, 1, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        requests_made = _audit_requests(result)
        # The 1h lookback sets the start; the API rejects ranges over 31 days, so the walk splits.
        assert [(r.param("start_time"), r.param("end_time"), r.param("cursor")) for r in requests_made] == [
            ("2026-04-20T00:00:00Z", "2026-05-20T00:00:00Z", None),
            ("2026-04-20T00:00:00Z", "2026-05-20T00:00:00Z", "b"),
            ("2026-05-20T00:00:00Z", "2026-06-01T00:00:00Z", None),
        ]
        assert {r.param("sort") for r in requests_made} == {"asc"}
        assert result.saved_states == [
            AutomoxResumeConfig(
                window_start="2026-04-20T00:00:00Z", cursor="b", incremental_param_value="2026-04-20T00:00:00Z"
            ),
            AutomoxResumeConfig(
                window_start="2026-05-20T00:00:00Z", cursor=None, incremental_param_value="2026-04-20T00:00:00Z"
            ),
        ]

    @time_machine.travel(AUDIT_NOW, tick=False)
    def test_full_refresh_starts_a_year_back(self) -> None:
        result = _driver().run(
            "audit_events",
            lambda request: ScriptedResponse(json=ORGS_BODY) if request.path == "/api/orgs" else _audit_page([]),
        )
        assert result.raised is None
        requests_made = _audit_requests(result)
        assert requests_made[0].param("start_time") == "2025-06-01T00:00:00Z"
        assert requests_made[-1].param("end_time") == "2026-06-01T00:00:00Z"
        assert len(requests_made) == 13

    @time_machine.travel(AUDIT_NOW, tick=False)
    def test_resume_continues_the_saved_window_and_cursor(self) -> None:
        result = _driver().run(
            "audit_events",
            [ScriptedResponse(json=ORGS_BODY), _audit_page([_audit_event("d")])],
            resume_state=AutomoxResumeConfig(window_start="2026-05-20T00:00:00Z", cursor="c"),
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["d"]
        assert [(r.param("start_time"), r.param("cursor")) for r in _audit_requests(result)] == [
            ("2026-05-20T00:00:00Z", "c")
        ]

    @parameterized.expand(
        [
            (
                "epoch_seconds_and_underscore_id",
                _audit_event("a", raw_data='{"password": "x"}'),
                "a",
                "2026-03-25T10:00:00.123456Z",
            ),
            ("epoch_milliseconds", _audit_event("a", time=1774432800000), "a", "2026-03-25T10:00:00.000000Z"),
            ("legacy_id", {"id": "b", "time": 1774432800}, "b", "2026-03-25T10:00:00.000000Z"),
            ("metadata_uid_only", {"metadata": {"uid": "m-1"}}, "m-1", None),
        ]
    )
    def test_shapes_an_event_into_a_row(
        self, _name: str, event: dict[str, Any], expected_id: str, expected_time: str | None
    ) -> None:
        row = _shape_audit_event(event)
        assert row["id"] == expected_id
        assert row["event_time"] == expected_time
        # The raw request payload can carry secrets, and `_id` is now `id`.
        assert "raw_data" not in row
        assert "_id" not in row


class TestAutomoxSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        config = AUTOMOX_ENDPOINTS[name]
        terminal_body: Any = {"data": []} if name in {"policy_runs", "remediation_issues", "audit_events"} else []
        result = _driver().run(
            name,
            lambda request: ScriptedResponse(json=ORGS_BODY if request.path == "/api/orgs" else terminal_body),
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_policy_runs_is_ascending_and_events_defers_watermark(self) -> None:
        # policy_runs requests an explicit ascending sort so per-batch watermark checkpoints are
        # safe; events has no documented ordering, so it must stay "desc" (watermark persisted only
        # on completed syncs).
        assert AUTOMOX_ENDPOINTS["policy_runs"].sort_mode == "asc"
        assert AUTOMOX_ENDPOINTS["events"].sort_mode == "desc"

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # Guards against accidentally partitioning on a churning field like last_refresh_time.
        assert {cfg.partition_key for cfg in AUTOMOX_ENDPOINTS.values() if cfg.partition_key} == {
            "create_time",
            "event_time",
            "run_time",
        }
