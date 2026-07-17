import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LangSmithSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith import LangSmithResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source import LangSmithSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestLangSmithSource:
    def setup_method(self):
        self.source = LangSmithSource()
        self.team_id = 123
        self.config = LangSmithSourceConfig(api_key="key", host=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LANGSMITH

    def test_config_fields(self):
        field_names = {f.name for f in self.source.get_source_config.fields}
        assert field_names == {"api_key", "host"}

        api_key = next(f for f in self.source.get_source_config.fields if f.name == "api_key")
        # The key is a secret; the wizard must render it as a password input.
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD

    def test_host_is_a_connection_host_field(self):
        # The key is sent to `host`; retargeting it must force re-entry of the key secret.
        assert self.source.connection_host_fields == ["host"]

    @pytest.mark.parametrize(
        "endpoint,expected_incremental",
        [
            ("runs", True),
            ("projects", False),
            ("datasets", False),
            ("examples", False),
            ("feedback", True),
            ("annotation_queues", False),
        ],
    )
    def test_get_schemas(self, endpoint, expected_incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        assert schema.detected_primary_keys == ["id"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_auth_errors_are_non_retryable(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is LangSmithResumeConfig

    def test_validate_credentials_collapses_blank_host_and_forwards_team_id(self):
        config = LangSmithSourceConfig(api_key="key", host="")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source.validate_langsmith_credentials",
            return_value=(True, None),
        ) as validate:
            result = self.source.validate_credentials(config, self.team_id)

        assert result == (True, None)
        # An empty host override collapses to None so the US-cloud default is used; team_id is
        # forwarded so the credential probe can SSRF-check the resolved host.
        validate.assert_called_once_with("key", None, self.team_id)

    @pytest.mark.parametrize(
        "host,expected_base_url",
        [
            (None, "https://api.smith.langchain.com"),
            ("https://eu.api.smith.langchain.com/", "https://eu.api.smith.langchain.com"),
        ],
    )
    def test_source_for_pipeline_resolves_base_url(self, host, expected_base_url):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"
        config = LangSmithSourceConfig(api_key="key", host=host)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source.langsmith_source"
        ) as langsmith_source:
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        _, kwargs = langsmith_source.call_args
        assert kwargs["endpoint"] == "runs"
        assert kwargs["base_url"] == expected_base_url
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-06-01T00:00:00Z"

    def test_source_for_pipeline_drops_incremental_value_on_full_refresh(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source.langsmith_source"
        ) as langsmith_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        _, kwargs = langsmith_source.call_args
        # A stale watermark must not leak into a full-refresh run.
        assert kwargs["db_incremental_field_last_value"] is None

    def test_documented_tables_render_from_static_catalog(self):
        # lists_tables_without_credentials must expose the table catalog (+ canonical descriptions)
        # for the public docs <SourceTables /> component without needing credentials.
        assert self.source.lists_tables_without_credentials is True

        tables = {t["name"]: t for t in self.source.get_documented_tables()}

        assert set(tables) == {"runs", "projects", "datasets", "examples", "feedback", "annotation_queues"}
        assert all(t["description"] for t in tables.values())
        assert "Incremental" in tables["runs"]["sync_methods"]
        assert tables["datasets"]["sync_methods"] == ["Full refresh"]
