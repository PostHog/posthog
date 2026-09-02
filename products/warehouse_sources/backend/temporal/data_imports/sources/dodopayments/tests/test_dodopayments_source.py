import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.settings import (
    DODOPAYMENTS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
    MODE_HOSTS,
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

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "DodoPayments"
        assert config.label == "Dodo Payments"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # unreleasedSource hides the source from every user, so a finished source must not set it.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/dodo-payments"

    def test_mode_field_offers_every_host(self):
        # Test and live data live on separate hosts with separate keys, so the mode cannot be
        # inferred and must be selectable.
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldSelectConfig) and f.name == "mode"
        )

        assert {option.value for option in field.options} == set(MODE_HOSTS)
        assert field.defaultValue in MODE_HOSTS

    @pytest.mark.parametrize(
        "observed_error, matches",
        [
            ("401 Client Error: Unauthorized for url: https://live.dodopayments.com/payments", True),
            ("403 Client Error: Forbidden for url: https://test.dodopayments.com/payouts", True),
            ("500 Server Error for url: https://live.dodopayments.com/payments", False),
            ("429 Client Error: Too Many Requests for url: https://live.dodopayments.com/payments", False),
        ],
    )
    def test_non_retryable_errors_cover_auth_failures_only(self, observed_error, matches):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors()) is matches

    def test_get_schemas_covers_the_endpoint_catalog(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == set(INCREMENTAL_ENDPOINTS)
        for schema in schemas:
            assert schema.incremental_fields == INCREMENTAL_FIELDS.get(schema.name, [])

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

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["payments"])

        assert [schema.name for schema in schemas] == ["payments"]

    def test_canonical_descriptions_are_keyed_by_schema_name(self):
        # A key that doesn't match a schema name is silently ignored, so the curated docs would
        # never reach the table.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

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
