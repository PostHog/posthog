from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kubecost import (
    KubecostSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.kubecost import (
    KubecostResumeConfig,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.source import KubecostSource

_TODAY_WINDOW = "2026-07-15T00:00:00Z,2026-07-16T00:00:00Z"

_SNAPSHOT_PRIMARY_KEYS = {
    "request_sizing_recommendations": ["clusterID", "namespace", "controllerKind", "controllerName", "containerName"],
    "audit_events": ["key"],
}


def _driver(host: str = "https://k.example.com") -> SourceDriver:
    return SourceDriver(KubecostSource(), KubecostSourceConfig(host=host, api_key="token"))


def _allocation_set(names: list[str]) -> dict[str, Any]:
    return {
        name: {
            "name": name,
            "window": {"start": "2026-07-14T00:00:00Z", "end": "2026-07-15T00:00:00Z"},
            "totalCost": 1.5,
        }
        for name in names
    }


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://kubecost.example.com", "https://kubecost.example.com"),
            ("kubecost.example.com", "https://kubecost.example.com"),
            ("https://kubecost.example.com/", "https://kubecost.example.com"),
            # The cost-model API prefix is re-appended per request, so a URL
            # entered with it must not produce `/model/model` paths.
            ("https://kubecost.example.com/model", "https://kubecost.example.com"),
            ("http://kubecost.internal:9090/model/", "http://kubecost.internal:9090"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://"])
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)


class TestValidateCredentials:
    def test_no_api_key_sends_no_auth_header(self) -> None:
        with scripted_network([ScriptedResponse(json={"code": 200, "data": [None]})]) as network:
            is_valid, _ = validate_credentials("https://kubecost.example.com", None)

        assert is_valid is True
        assert network.session_options[0]["headers"] is None
        assert "authorization" not in network.requests_log[0].headers

    @pytest.mark.parametrize(
        "status_code, expected_error",
        [
            (404, "unexpected status"),
        ],
    )
    def test_http_error_statuses(self, status_code: int, expected_error: str) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert expected_error in (error or "")
        assert network.requests_log[0].headers["authorization"] == "Bearer token"

    def test_error_envelope_fails_validation(self) -> None:
        with scripted_network([ScriptedResponse(json={"code": 500, "message": "boom"})]):
            is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert "boom" in (error or "")

    def test_non_json_response_fails_validation(self) -> None:
        with scripted_network([ScriptedResponse(body=b"not json")]):
            is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert "did not return a Kubecost API response" in (error or "")

    def test_unreachable_host_fails_validation(self) -> None:
        with scripted_network(always(ConnectionError("nope"))):
            is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert "Unable to reach" in (error or "")

    def test_api_key_over_plain_http_fails_before_any_request(self) -> None:
        # The bearer token must never ride a plaintext connection.
        with scripted_network([]) as network:
            is_valid, error = validate_credentials("http://kubecost.example.com", "token")

        assert is_valid is False
        assert "https" in (error or "")
        assert network.requests_log == []


class TestGetRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-07-15T10:00:00Z", tick=False):
            yield

    @pytest.mark.parametrize(
        "endpoint, data",
        [
            ("allocation_by_namespace", [_allocation_set(["__idle__", "argocd"])]),
            (
                "cloud_costs",
                {
                    "sets": [
                        {"cloudCosts": _allocation_set(["__idle__", "argocd"])},
                        {"cloudCosts": None},
                    ],
                    "window": {"start": "null", "end": "null"},
                },
            ),
        ],
    )
    def test_flattens_result_sets_and_injects_key_and_window(self, endpoint: str, data: Any) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"code": 200, "data": data})],
            resume_state=KubecostResumeConfig(next_date="2026-07-15"),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-15T00:00:00Z",
        )

        assert result.raised is None
        rows = result.rows
        assert {row["key"] for row in rows} == {"__idle__", "argocd"}
        # The server-reported window is preferred for the composite key columns.
        assert all(row["window_start"] == "2026-07-14T00:00:00Z" for row in rows)
        assert all(row["window_end"] == "2026-07-15T00:00:00Z" for row in rows)
        assert all(row["totalCost"] == 1.5 for row in rows)

    @pytest.mark.parametrize(
        "endpoint, expected_path, expected_aggregate, expected_window, expected_accumulate",
        [
            ("allocation_by_namespace", "/model/allocation", "namespace", _TODAY_WINDOW, "true"),
            ("allocation_by_controller", "/model/allocation", "controller", _TODAY_WINDOW, "true"),
            ("allocation_by_pod", "/model/allocation", "pod", _TODAY_WINDOW, "true"),
            ("allocation_by_cluster", "/model/allocation", "cluster", _TODAY_WINDOW, "true"),
            ("allocation_by_node", "/model/allocation", "node", _TODAY_WINDOW, "true"),
            ("allocation_by_service", "/model/allocation", "service", _TODAY_WINDOW, "true"),
            ("assets", "/model/assets", None, _TODAY_WINDOW, "true"),
            ("cloud_costs", "/model/cloudCost", None, _TODAY_WINDOW, "true"),
            (
                "external_costs",
                "/model/customCost/timeseries",
                "zone,accountName,chargeCategory,description,resourceName,resourceType,providerId,usageUnit,domain,costSource",
                _TODAY_WINDOW,
                "true",
            ),
            # Snapshot endpoints ignore the saved day and query their fixed lookback, or no window at all.
            ("request_sizing_recommendations", "/model/savings/requestSizingV2", None, "7d", None),
            ("audit_events", "/model/audit/events", None, None, None),
        ],
    )
    def test_endpoint_path_and_params(
        self,
        endpoint: str,
        expected_path: str,
        expected_aggregate: str | None,
        expected_window: str | None,
        expected_accumulate: str | None,
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"code": 200, "data": [None]})],
            resume_state=KubecostResumeConfig(next_date="2026-07-15"),
        )

        assert result.raised is None
        assert result.paths == [expected_path]
        assert result.requests[0].origin == "https://k.example.com"
        assert result.requests[0].param("aggregate") == expected_aggregate
        assert result.requests[0].param("window") == expected_window
        assert result.requests[0].param("accumulate") == expected_accumulate

    @pytest.mark.parametrize(
        "timeseries, expected_rows",
        [
            (
                [
                    {
                        "window": {"start": "2026-07-15T00:00:00Z", "end": "2026-07-15T01:00:00Z"},
                        "customCosts": [
                            {"id": "1", "aggregate": "us-east/acct/usage/datadog/observability", "billedCost": 2.5},
                            # No aggregate: the id is the key.
                            {"id": "2", "billedCost": 0.5},
                            "not-a-line-item",
                        ],
                    },
                    # A window with no data and a window without its own bounds.
                    {"window": {"start": "2026-07-15T01:00:00Z", "end": "2026-07-15T02:00:00Z"}, "customCosts": None},
                    {"customCosts": [{"aggregate": "eu-west/acct/usage/datadog/observability", "billedCost": 1.0}]},
                ],
                [
                    (
                        "us-east/acct/usage/datadog/observability",
                        "2026-07-15T00:00:00Z",
                        "2026-07-15T01:00:00Z",
                        2.5,
                    ),
                    ("2", "2026-07-15T00:00:00Z", "2026-07-15T01:00:00Z", 0.5),
                    (
                        "eu-west/acct/usage/datadog/observability",
                        "2026-07-15T00:00:00Z",
                        "2026-07-16T00:00:00Z",
                        1.0,
                    ),
                ],
            ),
            (None, []),
        ],
    )
    def test_external_costs_flattens_timeseries_line_items(
        self, timeseries: Any, expected_rows: list[tuple[str, str, str, float]]
    ) -> None:
        result = _driver().run(
            "external_costs",
            [ScriptedResponse(json={"code": 200, "data": {"window": {}, "timeseries": timeseries}})],
            resume_state=KubecostResumeConfig(next_date="2026-07-15"),
        )

        assert result.raised is None
        assert [
            (row["key"], row["window_start"], row["window_end"], row["billedCost"]) for row in result.rows
        ] == expected_rows

    @pytest.mark.parametrize(
        "body, expected_keys",
        [
            # The documented shape is a bare list.
            (
                [
                    {"clusterID": "c1", "namespace": "web", "controllerName": "api", "containerName": "app"},
                    {"clusterID": "c1", "namespace": "web", "controllerName": "api", "containerName": "sidecar"},
                    None,
                ],
                ["app", "sidecar"],
            ),
            (
                {"code": 200, "data": [{"clusterID": "c1", "containerName": "app"}]},
                ["app"],
            ),
            (
                {"TotalMonthlySavings": 4.2, "Count": 1, "Recommendations": [{"containerName": "app"}]},
                ["app"],
            ),
            ({"TotalMonthlySavings": 0, "Count": 0, "Recommendations": None}, []),
        ],
    )
    def test_request_sizing_accepts_documented_response_shapes(self, body: Any, expected_keys: list[str]) -> None:
        result = _driver().run(
            "request_sizing_recommendations",
            [ScriptedResponse(json=body)],
            resume_state=KubecostResumeConfig(next_date="2026-07-01"),
        )

        assert result.raised is None
        assert [row["containerName"] for row in result.rows] == expected_keys
        # One request for the current state: no day walk and no checkpoint.
        assert len(result.requests) == 1
        assert result.saved_states == []

    @pytest.mark.parametrize(
        "event, expected_key",
        [
            (
                {
                    "eventType": "add",
                    "resourceType": "deployment",
                    "timestamp": "2026-07-14T13:58:44.552788548Z",
                    "properties": {"cluster": "cluster-one", "name": "web", "namespace": "shop"},
                },
                "2026-07-14T13:58:44.552788548Z/add/deployment/cluster-one/shop/web",
            ),
            (
                {"eventType": "delete", "timestamp": "2026-07-14T14:00:00Z", "properties": None},
                "2026-07-14T14:00:00Z/delete////",
            ),
        ],
    )
    def test_audit_events_get_a_key_built_from_the_change(self, event: dict[str, Any], expected_key: str) -> None:
        result = _driver().run("audit_events", [ScriptedResponse(json={"code": 200, "data": [event]})])

        assert result.raised is None
        assert [row["key"] for row in result.rows] == [expected_key]
        assert result.rows[0]["eventType"] == event["eventType"]

    @pytest.mark.parametrize("endpoint", ["allocation_by_namespace", "audit_events"])
    def test_api_key_over_plain_http_raises_before_any_request(self, endpoint: str) -> None:
        result = _driver("http://kubecost.example.com").run(endpoint, [])

        assert isinstance(result.raised, ValueError)
        assert "https" in str(result.raised)
        assert result.requests == []

    @pytest.mark.parametrize(
        "endpoint, body",
        [
            ("allocation_by_namespace", {"code": 400, "message": "bad request"}),
            # A windowed endpoint must not take a bare body for a Kubecost response.
            ("allocation_by_namespace", {"message": "bad request"}),
            ("audit_events", {"code": 400, "message": "bad request"}),
            ("request_sizing_recommendations", {"code": 400, "message": "bad request"}),
        ],
    )
    def test_error_envelope_raises(self, endpoint: str, body: dict[str, Any]) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=body)],
            resume_state=KubecostResumeConfig(next_date="2026-07-15"),
        )

        assert isinstance(result.raised, ValueError)
        assert "bad request" in str(result.raised)

    def test_walks_one_window_per_day_and_checkpoints_the_next_day(self) -> None:
        result = _driver().run(
            "allocation_by_namespace",
            [ScriptedResponse(json={"code": 200, "data": [None]})] * 3,
            resume_state=KubecostResumeConfig(next_date="2026-07-13"),
        )

        assert result.raised is None
        assert len(result.requests) == 3
        # The last day has no successor, so it is not checkpointed.
        assert result.saved_states == [
            KubecostResumeConfig(next_date="2026-07-14"),
            KubecostResumeConfig(next_date="2026-07-15"),
        ]


class TestKubecostSourceResponse:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-07-15T10:00:00Z", tick=False):
            yield

    @pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if e not in _SNAPSHOT_PRIMARY_KEYS])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"code": 200, "data": [None]})],
            resume_state=KubecostResumeConfig(next_date="2026-07-15"),
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        # The result-set key is only unique within one window, so the window
        # start must be part of the composite key.
        assert response.primary_keys == ["key", "window_start"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["window_start"]

    @pytest.mark.parametrize("endpoint, expected_primary_keys", list(_SNAPSHOT_PRIMARY_KEYS.items()))
    def test_snapshot_response_metadata(self, endpoint: str, expected_primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"code": 200, "data": []})])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.primary_keys == expected_primary_keys
        # A snapshot is not read in window order, so it makes no ordering promise.
        assert response.sort_mode is None
        assert response.partition_keys is None
