import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JustCallSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.justcall import JustCallResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source import JustCallSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source"


class TestJustCallSource:
    def setup_method(self):
        self.source = JustCallSource()
        self.team_id = 123
        self.config = JustCallSourceConfig(api_key="key", api_secret="secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.JUSTCALL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "JustCall"
        assert config.label == "JustCall"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/justcall.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "api_secret"]

    @pytest.mark.parametrize("field_name", ["api_key", "api_secret"])
    def test_credential_fields_are_secret_passwords(self, field_name):
        config = self.source.get_source_config
        secret_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.justcall.io/v2.1/calls?page=0",
            "403 Client Error: Forbidden for url: https://api.justcall.io/v2.1/texts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.justcall.io/v2.1/calls",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_time_filterable_endpoints_support_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        # Only calls, texts, and sales dialer calls expose JustCall's from_datetime filter.
        assert incremental == {"calls", "texts", "sales_dialer_calls"}

        assert schemas["calls"].incremental_fields == INCREMENTAL_FIELDS["calls"]
        assert schemas["contacts"].incremental_fields == []
        assert schemas["contacts"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [s.name for s in schemas] == ["calls"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self):
        # The endpoint catalog is static (no I/O), so it's safe to render in public docs.
        assert JustCallSource.lists_tables_without_credentials is True

    def test_documented_tables_render_from_static_catalog(self):
        tables = self.source.get_documented_tables()
        names = {t["name"] for t in tables}
        assert set(ENDPOINTS).issubset(names)
        # Canonical descriptions flow through to the rendered docs.
        calls = next(t for t in tables if t["name"] == "calls")
        assert calls["description"]

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        for endpoint in ENDPOINTS:
            assert endpoint in descriptions, f"missing canonical description for {endpoint}"
            assert descriptions[endpoint]["columns"]

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid JustCall API credentials"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_justcall_credentials")
    def test_validate_credentials(self, mock_validate, probe_result, expected_valid, expected_message):
        mock_validate.return_value = probe_result

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.api_secret)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JustCallResumeConfig

    @mock.patch(f"{SOURCE_MODULE}.justcall_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_justcall_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2021-08-25"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_justcall_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["api_secret"] == "secret"
        assert kwargs["endpoint"] == "calls"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2021-08-25"

    @mock.patch(f"{SOURCE_MODULE}.justcall_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_justcall_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2021-08-25"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_justcall_source.call_args.kwargs["db_incremental_field_last_value"] is None
