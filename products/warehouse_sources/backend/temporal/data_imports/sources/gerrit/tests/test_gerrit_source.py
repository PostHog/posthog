from datetime import datetime

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GerritSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.gerrit import GerritResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.source import GerritSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGerritSource:
    def setup_method(self):
        self.source = GerritSource()
        self.team_id = 123
        self.config = GerritSourceConfig(host="https://gerrit.example.com", username="bot", http_password="secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GERRIT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Gerrit"
        assert config.label == "Gerrit"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/gerrit.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/gerrit"

        host_field, username_field, password_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert (host_field.name, host_field.required, host_field.secret) == ("host", True, False)
        assert isinstance(username_field, SourceFieldInputConfig)
        assert (username_field.name, username_field.required, username_field.secret) == ("username", False, False)
        assert isinstance(password_field, SourceFieldInputConfig)
        assert (password_field.name, password_field.required, password_field.secret) == ("http_password", False, True)

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_changes_supports_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["changes"].supports_incremental is True
        assert [f["field"] for f in schemas["changes"].incremental_fields] == ["updated"]
        for name in ("accounts", "projects", "groups"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["changes"])
        assert [s.name for s in schemas] == ["changes"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize("mock_return", [(True, None), (False, "Invalid Gerrit username or HTTP password")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.source.validate_gerrit_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="groups")

        assert result == mock_return
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["host"] == "https://gerrit.example.com"
        assert kwargs["username"] == "bot"
        assert kwargs["http_password"] == "secret"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["schema_name"] == "groups"

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is GerritResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.source.gerrit_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_gerrit_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "changes"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = datetime(2026, 7, 15, 16, 15, 24)
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_gerrit_source.call_args.kwargs
        assert kwargs["host"] == "https://gerrit.example.com"
        assert kwargs["username"] == "bot"
        assert kwargs["http_password"] == "secret"
        assert kwargs["endpoint"] == "changes"
        assert kwargs["team_id"] == 42
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == datetime(2026, 7, 15, 16, 15, 24)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.source.gerrit_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_gerrit_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "changes"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = datetime(2026, 7, 15, 16, 15, 24)

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gerrit_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    def test_documented_tables_render_without_credentials(self):
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables.keys()) == set(ENDPOINTS)
        assert "Incremental" in tables["changes"]["sync_methods"]
        assert tables["changes"]["description"]
