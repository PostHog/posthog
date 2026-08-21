import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.settings import (
    DODOPAYMENTS_ENDPOINTS,
    RESTATED_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.source import DodoPaymentsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dodopayments import (
    DodoPaymentsSourceConfig,
)

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.source.api_client"


class TestDodoPaymentsSource:
    def setup_method(self):
        self.source = DodoPaymentsSource()
        self.team_id = 123
        self.config = DodoPaymentsSourceConfig(api_key="test-api-key", mode="live")

    def test_get_schemas_declares_per_endpoint_primary_keys(self):
        # A shared `id` default would be wrong for payments/subscriptions/refunds and would seed
        # duplicate rows every merge.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        for name, endpoint in DODOPAYMENTS_ENDPOINTS.items():
            assert schemas[name].detected_primary_keys == endpoint.primary_keys

    def test_restated_endpoints_get_a_default_lookback(self):
        # Dodo only filters on created_at, so a bare cursor would freeze status columns at their
        # first-imported values on tables whose rows are restated in place.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        with_lookback = {
            name for name, schema in schemas.items() if schema.default_incremental_lookback_seconds is not None
        }
        assert with_lookback == {name for name, e in DODOPAYMENTS_ENDPOINTS.items() if e.restated}
        assert schemas["payments"].default_incremental_lookback_seconds == RESTATED_LOOKBACK_SECONDS

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message_fragment",
        [
            ((True, 200), True, None),
            ((False, 401), False, "rejected the API key"),
            ((False, 403), False, "permission to read"),
            ((False, 429), False, "rate limiting"),
            ((False, 500), False, "server error"),
            ((False, None), False, "Could not reach"),
        ],
    )
    @mock.patch(f"{API_CLIENT_PATCH}.validate_credentials")
    def test_validate_credentials_maps_probe_results(
        self, mock_validate, probe_result, expected_valid, expected_message_fragment
    ):
        mock_validate.return_value = probe_result

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message
        mock_validate.assert_called_once_with("test-api-key", "live")
