import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OktaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import OktaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.source import OktaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOktaSource:
    def setup_method(self):
        self.source = OktaSource()
        self.team_id = 123
        self.config = OktaSourceConfig(okta_domain="example.okta.com", api_key="00token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OKTA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Okta"
        assert config.label == "Okta"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/okta.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["okta_domain", "api_key"]

        domain_field, token_field = config.fields
        assert isinstance(domain_field, SourceFieldInputConfig)
        assert domain_field.type == SourceFieldInputConfigType.TEXT
        assert domain_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("users", True),
            ("groups", True),
            ("applications", False),
            ("logs", True),
            ("group_rules", False),
            ("user_types", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_logs_schema_has_lookback_description(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "90 days" in (schemas["logs"].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert len(schemas) == 1
        assert schemas[0].name == "users"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected",
        [
            ((True, None), (True, None)),
            ((False, "Invalid Okta API token"), (False, "Invalid Okta API token")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.okta.source.validate_okta_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="users")

        assert result == expected
        mock_validate.assert_called_once_with(self.config.okta_domain, self.config.api_key, "users", self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OktaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.okta.source.okta_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_okta_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000Z"
        inputs.incremental_field = "lastUpdated"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_okta_source.assert_called_once()
        kwargs = mock_okta_source.call_args.kwargs
        assert kwargs["domain"] == "example.okta.com"
        assert kwargs["api_key"] == "00token"
        assert kwargs["endpoint"] == "users"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "lastUpdated"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.okta.source.okta_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_okta_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "group_rules"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_okta_source.call_args.kwargs["db_incremental_field_last_value"] is None
