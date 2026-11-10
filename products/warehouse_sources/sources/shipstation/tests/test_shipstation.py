from datetime import UTC, date, datetime

import pytest

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network
from products.warehouse_sources.sources.shipstation._config import ShipStationSourceConfig
from products.warehouse_sources.sources.shipstation.settings import (
    PAGE_SIZE,
    SHIPSTATION_ENDPOINTS,
    SHIPSTATION_V1,
    SHIPSTATION_V2,
)
from products.warehouse_sources.sources.shipstation.shipstation import (
    SHIPSTATION_DIALECTS,
    ShipStationResumeConfig,
    _build_params,
    _format_date_filter,
    validate_credentials,
)
from products.warehouse_sources.sources.shipstation.source import ShipStationSource

V2_DIALECT = SHIPSTATION_DIALECTS[SHIPSTATION_V2]


def _driver() -> SourceDriver:
    return SourceDriver(ShipStationSource(), ShipStationSourceConfig(api_key="key", api_secret="secret"))


class TestFormatDateFilter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            # Naive datetimes are assumed to already be Pacific (from API rows).
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02 03:04:05"),
            # Aware datetimes are converted to Pacific (UTC-8 in January).
            (datetime(2024, 1, 2, 11, 4, 5, tzinfo=UTC), "2024-01-02 03:04:05"),
            (date(2024, 1, 2), "2024-01-02 00:00:00"),
            ("2024-01-02T03:04:05.0000000", "2024-01-02 03:04:05"),
            ("2024-01-02 03:04:05", "2024-01-02 03:04:05"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_date_filter(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            # v2 (ShipEngine) filters in ISO 8601 UTC, not Pacific.
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            # Naive values from v2 rows are already UTC.
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05.657Z", "2024-01-02T03:04:05.657Z"),
        ],
    )
    def test_format_values_v2_uses_iso_utc(self, value, expected):
        assert _format_date_filter(value, V2_DIALECT) == expected


class TestBuildParams:
    @pytest.mark.parametrize("endpoint", ["stores", "warehouses"])
    def test_unpaginated_endpoints_have_no_params(self, endpoint):
        params = _build_params(
            SHIPSTATION_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params == {}


class TestValidateCredentials:
    def test_v1_requires_secret_without_probing(self):
        # v1 authenticates with a key + secret pair; a missing secret must fail before any request.
        ok, error = validate_credentials("key", None, SHIPSTATION_V1)
        assert ok is False
        assert error is not None and "secret" in error.lower()

    def test_v2_probes_v2_host_with_api_key_only(self):
        with scripted_network([ScriptedResponse(status=200)]) as network:
            ok, _error = validate_credentials("key", None, SHIPSTATION_V2)

        assert ok is True
        assert network.requests_log[0].url == "https://api.shipstation.com/v2/carriers"


class TestExtractionShapes:
    """The framework's data_selector replaces the old _extract_items helper; assert the same
    row-level result for the response shapes the real API returns."""

    @pytest.mark.parametrize("body", [{}, {"orders": None}])
    def test_missing_or_null_data_key_yields_no_rows(self, body):
        # ``pages`` absent + no/empty data ends pagination after one short/empty page.
        result = _driver().run("orders", [ScriptedResponse(json=body)], api_version=SHIPSTATION_V1)

        assert result.raised is None
        assert result.rows == []

    @pytest.mark.parametrize(
        "endpoint, row, path, params",
        [
            ("users", {"userId": "user-a", "name": "Warehouse operator"}, "/users", {"showInactive": "true"}),
            ("marketplaces", {"marketplaceId": 1, "name": "Example shop"}, "/stores/marketplaces", {}),
        ],
    )
    def test_v1_reference_tables(
        self, endpoint: str, row: dict[str, str | int], path: str, params: dict[str, str]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[row])], api_version=SHIPSTATION_V1)

        assert result.raised is None
        assert result.rows == [row]
        assert result.paths == [path]
        assert dict(result.requests[0].query) == {key: (value,) for key, value in params.items()}

    @pytest.mark.parametrize("api_version", [SHIPSTATION_V1, SHIPSTATION_V2])
    @pytest.mark.parametrize("endpoint", ["services", "packages"])
    @pytest.mark.parametrize("resume", [False, True])
    def test_carrier_lookups(self, api_version: str, endpoint: str, resume: bool) -> None:
        is_v2 = api_version == SHIPSTATION_V2
        parent_key = "carrier_id" if is_v2 else "code"
        carrier_key = "carrier_id" if is_v2 else "carrierCode"
        code_key = ("service_code" if endpoint == "services" else "package_code") if is_v2 else "code"
        child_path = f"/v2/carriers/carrier-a/{endpoint}" if is_v2 else f"/carriers/list{endpoint}"
        completed_path = f"/carriers/carrier-a/{endpoint}" if is_v2 else f"{child_path}?carrierCode=carrier-a"
        parents = [{parent_key: carrier} for carrier in ["carrier-a", "carrier-empty", "carrier-b"]]
        child = {code_key: "shared-code", "name": "Example type"}
        body = {"carriers": parents} if is_v2 else parents
        child_body = {endpoint: [child]} if is_v2 else [child]
        empty_body = {endpoint: []} if is_v2 else []
        script = [ScriptedResponse(json=body)]
        if not resume:
            script.append(ScriptedResponse(json=child_body))
        script.extend([ScriptedResponse(json=empty_body), ScriptedResponse(json=child_body)])

        result = _driver().run(
            endpoint,
            script,
            api_version=api_version,
            resume_state=ShipStationResumeConfig(
                fanout_state={"completed": [completed_path], "current": None, "child_state": None}
            )
            if resume
            else None,
        )

        assert result.raised is None
        expected_carriers = ["carrier-b"] if resume else ["carrier-a", "carrier-b"]
        assert result.rows == [{**child, carrier_key: carrier} for carrier in expected_carriers]
        requested_carriers = ["carrier-empty", "carrier-b"] if resume else ["carrier-a", "carrier-empty", "carrier-b"]
        if is_v2:
            assert result.paths == [
                "/v2/carriers",
                *[f"/v2/carriers/{carrier}/{endpoint}" for carrier in requested_carriers],
            ]
        else:
            assert result.paths == ["/carriers", *[child_path] * len(requested_carriers)]
            assert result.params("carrierCode") == [None, *requested_carriers]
        assert result.params("page") == [None] * len(result.requests)
        assert result.params("pageSize") == [None] * len(result.requests)
        assert result.params("page_size") == [None] * len(result.requests)
        assert result.response is not None
        assert result.response.primary_keys == [carrier_key, code_key]
        assert result.final_state is not None
        completed = result.final_state.fanout_state["completed"]
        assert len(completed) == 3
        assert completed_path in completed


class TestPagination:
    def test_v2_users_paginates_with_the_endpoint_page_limit(self) -> None:
        result = _driver().run(
            "users",
            [
                ScriptedResponse(json={"users": [{"user_id": "user-a"}], "page": 1, "pages": 2}),
                ScriptedResponse(json={"users": [{"user_id": "user-b"}], "page": 2, "pages": 2}),
            ],
            api_version=SHIPSTATION_V2,
        )

        assert result.raised is None
        assert result.rows == [{"user_id": "user-a"}, {"user_id": "user-b"}]
        assert result.paths == ["/v2/users", "/v2/users"]
        assert result.params("page") == ["1", "2"]
        assert result.params("page_size") == ["100", "100"]

    def test_paginates_using_pages_total(self):
        result = _driver().run(
            "orders",
            [
                ScriptedResponse(json={"orders": [{"orderId": 1}], "page": 1, "pages": 2}),
                ScriptedResponse(json={"orders": [{"orderId": 2}], "page": 2, "pages": 2}),
            ],
            api_version=SHIPSTATION_V1,
        )

        assert [row["orderId"] for row in result.rows] == [1, 2]
        assert result.params("page") == ["1", "2"]
        assert result.params("pageSize") == [str(PAGE_SIZE)] * 2
        # Checkpoint saved once after the first page (points at page 2); the ``pages`` total ends it.
        assert result.saved_states == [ShipStationResumeConfig(page=2)]

    def test_resumes_from_saved_page(self):
        result = _driver().run(
            "orders",
            [ScriptedResponse(json={"orders": [{"orderId": 9}], "page": 5, "pages": 5})],
            resume_state=ShipStationResumeConfig(page=5),
            api_version=SHIPSTATION_V1,
        )

        assert [row["orderId"] for row in result.rows] == [9]
        assert result.params("page") == ["5"]
        assert len(result.requests) == 1

    def test_incremental_request_includes_filter(self):
        result = _driver().run(
            "orders",
            [ScriptedResponse(json={"orders": [], "pages": 0})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-02T03:04:05.0000000",
            incremental_field="modifyDate",
            api_version=SHIPSTATION_V1,
        )

        assert result.params("modifyDateStart") == ["2024-01-02 03:04:05"]
        assert result.params("sortBy") == ["ModifyDate"]
        assert result.params("sortDir") == ["ASC"]
