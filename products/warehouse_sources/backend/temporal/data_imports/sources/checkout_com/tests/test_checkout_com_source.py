import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source import CheckoutComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkoutcom import (
    CheckoutComSourceConfig,
)

DISCOVER_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.discover_report_types"
)
_STATIC_SCHEMAS = ["disputes", "reports", "payments", "payment_actions", "customers", "instruments"]


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


class TestCheckoutComSource:
    def setup_method(self):
        self.source = CheckoutComSource()
        self.team_id = 123
        self.config = CheckoutComSourceConfig(environment="production", client_id="ack_id", client_secret="secret")

    @mock.patch(DISCOVER_PATCH)
    def test_get_schemas_static_catalog(self, mock_discover):
        mock_discover.return_value = {}

        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == _STATIC_SCHEMAS
        assert all(schema.supports_incremental for schema in schemas)
        cursors = {s.name: [f["field"] for f in s.incremental_fields] for s in schemas}
        assert cursors == {
            "disputes": ["last_update"],
            "reports": ["created_on"],
            "payments": ["requested_on"],
            "payment_actions": ["payment_requested_on"],
            "customers": ["payment_requested_on"],
            "instruments": ["payment_requested_on"],
        }

    @mock.patch(DISCOVER_PATCH)
    def test_get_schemas_appends_discovered_report_tables(self, mock_discover):
        mock_discover.return_value = {"payments_report": "Payments", "financial_actions_report": "FinancialActions"}

        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == [*_STATIC_SCHEMAS, "financial_actions_report", "payments_report"]
        report_table = next(s for s in schemas if s.name == "financial_actions_report")
        assert report_table.supports_incremental is True
        # Boundary re-reads on the inclusive `created_after` filter make append unsafe.
        assert report_table.supports_append is False
        assert [f["field"] for f in report_table.incremental_fields] == ["report_created_on"]
        mock_discover.assert_called_once_with("production", "ack_id", "secret")

    @mock.patch(DISCOVER_PATCH)
    def test_get_schemas_without_credentials_never_discovers(self, mock_discover):
        config = CheckoutComSourceConfig(environment="production", client_id="", client_secret="")

        schemas = self.source.get_schemas(config, self.team_id)

        # The credential-free path serves public docs and placeholder configs, so it
        # must never reach the API.
        mock_discover.assert_not_called()
        assert [s.name for s in schemas] == _STATIC_SCHEMAS

    @pytest.mark.parametrize("status", [401, 403])
    @mock.patch(DISCOVER_PATCH)
    def test_get_schemas_scope_denied_discovery_degrades_to_static(self, mock_discover, status):
        # A key without the reports scope is a valid configuration; its correct listing
        # is the static catalog.
        mock_discover.side_effect = _http_error(status)

        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == _STATIC_SCHEMAS

    @pytest.mark.parametrize(
        "error",
        [_http_error(429), _http_error(500), requests.ConnectionError("connection reset")],
    )
    @mock.patch(DISCOVER_PATCH)
    def test_get_schemas_transient_discovery_failure_propagates(self, mock_discover, error):
        # Degrading to the static catalog on a transient failure would make scheduled
        # discovery prune the report-type schemas it discovered on earlier runs.
        mock_discover.side_effect = error

        with pytest.raises(type(error)):
            self.source.get_schemas(self.config, self.team_id)

    @pytest.mark.parametrize(
        "names, expected",
        [
            (["nope"], []),
            (["financial_actions_report"], ["financial_actions_report"]),
        ],
    )
    @mock.patch(DISCOVER_PATCH)
    def test_get_schemas_names_filter_spans_static_and_discovered(self, mock_discover, names, expected):
        mock_discover.return_value = {"financial_actions_report": "FinancialActions"}

        schemas = self.source.get_schemas(self.config, self.team_id, names=names)

        assert [s.name for s in schemas] == expected

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Checkout.com access keys"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.validate_checkout_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("production", "ack_id", "secret")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.checkout_com_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_co_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "disputes"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_co_source.assert_called_once()
        kwargs = mock_co_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["client_id"] == "ack_id"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["endpoint"] == "disputes"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.checkout_com_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_co_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "disputes"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_co_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @pytest.mark.parametrize("schema_name", ["reports", "financial_actions_report"])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.checkout_com_reports_source"
    )
    def test_source_for_pipeline_routes_report_schemas(self, mock_reports_source, schema_name):
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_reports_source.assert_called_once()
        kwargs = mock_reports_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["client_id"] == "ack_id"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["schema_name"] == schema_name
        assert kwargs["logger"] is inputs.logger
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @pytest.mark.parametrize("schema_name", ["payments", "payment_actions", "customers", "instruments"])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.checkout_com_payments_source"
    )
    def test_source_for_pipeline_routes_payments_schemas(self, mock_payments_source, schema_name):
        config = CheckoutComSourceConfig(
            environment="production", client_id="ack_id", client_secret="secret", start_date="2024-01-01"
        )
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        mock_payments_source.assert_called_once()
        kwargs = mock_payments_source.call_args.kwargs
        assert kwargs["schema_name"] == schema_name
        assert kwargs["start_date"] == "2024-01-01"
        assert kwargs["logger"] is inputs.logger
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"
