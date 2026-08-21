import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pabblysubscriptionsbilling import (
    PabblySubscriptionsBillingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pabbly_subscriptions_billing.source import (
    PabblySubscriptionsBillingSource,
)


class TestPabblySubscriptionsBillingSource:
    def setup_method(self) -> None:
        self.source = PabblySubscriptionsBillingSource()
        self.team_id = 123
        self.config = PabblySubscriptionsBillingSourceConfig(api_key="pabbly-key", secret_key="pabbly-secret")

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
