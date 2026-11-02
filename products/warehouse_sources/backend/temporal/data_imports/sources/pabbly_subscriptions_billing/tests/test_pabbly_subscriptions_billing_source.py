from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pabblysubscriptionsbilling import (
    PabblySubscriptionsBillingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.settings import (
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.source import (
    PabblySubscriptionsBillingSource,
)


class TestPabblySubscriptionsBillingSource:
    def setup_method(self) -> None:
        self.source = PabblySubscriptionsBillingSource()
        self.team_id = 123
        self.config = PabblySubscriptionsBillingSourceConfig(api_key="pabbly-key", secret_key="pabbly-secret")

    def test_no_connection_host_fields(self) -> None:
        # Both fields are secrets and the base URL is hardcoded, so there is no non-secret field
        # an editor could retarget to reuse a preserved credential against another host.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_validate_credentials_delegates_with_both_keys(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Pabbly Subscription Billing API key or secret key")
        assert network.requests_log[0].path == "/api/v1/customers"
        assert network.requests_log[0].headers["authorization"] == "Basic cGFiYmx5LWtleTpwYWJibHktc2VjcmV0"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.source.pabbly_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pabbly-key"
        assert kwargs["secret_key"] == "pabbly-secret"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
