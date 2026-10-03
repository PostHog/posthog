import pytest
from unittest import mock

from parameterized import parameterized

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

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["subscriptions"])
        assert len(schemas) == 1
        assert schemas[0].name == "subscriptions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://payments.pabbly.com/api/v1/customers?page=1&limit=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://payments.pabbly.com/api/v1/subscriptions?page=1&limit=100",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://payments.pabbly.com/api/v1/customers",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://payments.pabbly.com/api/v1/subscriptions",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_both_keys(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in the transport module; here we only assert the
        # source probes with the configured key pair and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Pabbly Subscription Billing API key or secret key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("pabbly-key", "pabbly-secret")
        assert result == (False, "Invalid Pabbly Subscription Billing API key or secret key")

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

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Pabbly Subscription Billing schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
