import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.settings import (
    ENDPOINTS,
    ORDER_FAN_OUT_ENDPOINTS,
    PARTITION_FIELDS,
    V2_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigcommerce.source import BigCommerceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigcommerce import (
    BigCommerceSourceConfig,
)


class TestBigCommerceSource:
    def setup_method(self) -> None:
        self.source = BigCommerceSource()
        self.team_id = 123
        self.config = BigCommerceSourceConfig(store_hash="store123", access_token="test-token")

    @staticmethod
    def _empty_page(endpoint: str) -> ScriptedResponse:
        # Per-order endpoints fan out over the V2 orders listing.
        if endpoint in V2_ENDPOINTS | ORDER_FAN_OUT_ENDPOINTS:
            return ScriptedResponse(json=[])
        return ScriptedResponse(json={"data": [], "meta": {"pagination": {"current_page": 1, "total_pages": 1}}})

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "orders", True),
            (401, None, False),
            (403, None, True),  # token valid but scoped narrower than the probe endpoint -> allowed at create
            (403, "orders", False),  # rejected for a specific schema check
            (404, None, False),
            (None, None, False),  # connection error
        ],
    )
    def test_validate_credentials(self, status: int | None, schema_name: str | None, expected_valid: bool) -> None:
        script = [ScriptedResponse(status=status)] if status is not None else always(ConnectionError("boom"))
        with scripted_network(script) as network:
            is_valid, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/stores/store123/v3/catalog/products"}
        assert {request.headers["x-auth-token"] for request in network.requests_log} == {"test-token"}

    def test_validate_credentials_missing_fields(self) -> None:
        config = BigCommerceSourceConfig(store_hash="", access_token="")
        with scripted_network([]) as network:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message == "Missing BigCommerce credentials"
        assert network.requests_log == []

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "orders",
            [self._empty_page("orders")],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00",
        )

        assert result.raised is None
        assert result.requests[0].path == "/stores/store123/v2/orders"
        assert result.requests[0].headers["x-auth-token"] == "test-token"
        assert result.requests[0].param("min_date_modified") == "2024-01-01T00:00:00"
        response = result.response
        assert response is not None
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "desc"

    def test_source_for_pipeline_full_refresh_drops_last_value(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "customers",
            [self._empty_page("customers")],
            db_incremental_field_last_value="2024-01-01T00:00:00",
        )

        assert result.raised is None
        assert result.requests[0].param("date_modified:min") is None
        response = result.response
        assert response is not None
        assert response.sort_mode == "asc"

    def test_source_for_pipeline_ignores_incremental_for_non_incremental_endpoint(self) -> None:
        # Categories has no date_modified field; a stale schema requesting incremental sync
        # must fall back to full refresh instead of sending a cursor the endpoint can't use.
        result = SourceDriver(self.source, self.config).run(
            "categories",
            [self._empty_page("categories")],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00",
        )

        assert result.raised is None
        assert result.requests[0].param("date_modified:min") is None
        response = result.response
        assert response is not None
        assert response.sort_mode == "asc"

    @parameterized.expand(sorted(ENDPOINTS))
    def test_source_for_pipeline_partitioning(self, endpoint: str) -> None:
        result = SourceDriver(self.source, self.config).run(endpoint, [self._empty_page(endpoint)])

        assert result.raised is None
        response = result.response
        assert response is not None
        expected_key = PARTITION_FIELDS.get(endpoint)
        if expected_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [expected_key]
        else:
            assert response.partition_keys is None
