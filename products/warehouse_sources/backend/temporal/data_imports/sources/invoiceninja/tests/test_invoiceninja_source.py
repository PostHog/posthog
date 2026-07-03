import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InvoiceninjaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.invoiceninja import (
    InvoiceNinjaResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.source import InvoiceninjaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestInvoiceninjaSource:
    def setup_method(self):
        self.source = InvoiceninjaSource()
        self.team_id = 123
        self.config = InvoiceninjaSourceConfig(api_token="tok", base_url=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.INVOICENINJA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Invoiceninja"
        assert config.label == "Invoice Ninja"
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/invoiceninja.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/invoiceninja"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_token", "base_url"]

        api_token_field, base_url_field = config.fields
        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.secret is True
        assert api_token_field.required is True

        assert isinstance(base_url_field, SourceFieldInputConfig)
        assert base_url_field.type == SourceFieldInputConfigType.TEXT
        assert base_url_field.secret is False
        assert base_url_field.required is False

    def test_connection_host_fields_force_secret_reentry(self):
        # The API token is sent to base_url, so retargeting it must re-require the token.
        assert self.source.connection_host_fields == ["base_url"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self):
        # Incremental is deferred until the server-side filter + sort order are verified against the
        # live API, so every stream ships full-refresh only.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["invoices"])
        assert len(schemas) == 1
        assert schemas[0].name == "invoices"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected",
        [
            ((True, None), (True, None)),
            ((False, "Invalid Invoice Ninja API token"), (False, "Invalid Invoice Ninja API token")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.source.validate_invoiceninja_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="invoices")

        assert result == expected
        mock_validate.assert_called_once_with(self.config.base_url, self.config.api_token, "invoices", self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is InvoiceNinjaResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.source.invoiceninja_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_invoiceninja_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.team_id = 42
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_invoiceninja_source.assert_called_once()
        kwargs = mock_invoiceninja_source.call_args.kwargs
        assert kwargs["base_url"] == self.config.base_url
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42

    def test_canonical_descriptions_cover_core_tables(self):
        descriptions = self.source.get_canonical_descriptions()
        # Curated docs only describe endpoints we actually expose.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "clients" in descriptions
        assert "invoices" in descriptions
        assert "payments" in descriptions
