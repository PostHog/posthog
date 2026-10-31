from datetime import UTC, date, datetime

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shipstation import (
    ShipStationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    SHIPSTATION_ENDPOINTS,
    SHIPSTATION_V1,
    SHIPSTATION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation import (
    PAGE_SIZE,
    SHIPSTATION_DIALECTS,
    ShipStationResumeConfig,
    _build_params,
    _format_date_filter,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.source import ShipStationSource

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


class TestPagination:
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
