import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.n8n import N8nSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.source import N8nSource


class TestN8nSource:
    def setup_method(self):
        self.source = N8nSource()
        self.team_id = 123
        self.config = N8nSourceConfig(host="https://myorg.app.n8n.cloud", api_key="key")

    def test_connection_host_fields_cover_host(self):
        # The instance URL decides where the stored API key gets sent.
        assert self.source.connection_host_fields == ["host"]

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static endpoint catalog, so the public docs can render tables.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://myorg.app.n8n.cloud/api/v1/workflows",
            "403 Client Error: Forbidden for url: https://myorg.app.n8n.cloud/api/v1/users",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "error",
        [
            "500 Server Error for url: https://myorg.app.n8n.cloud/api/v1/workflows",
            "429 Client Error: Too Many Requests",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_failures(self, error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas_are_all_full_refresh(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # n8n exposes no server-side timestamp filter, so nothing is incremental.
        assert all(not schema.supports_incremental for schema in schemas.values())
        assert all(not schema.supports_append for schema in schemas.values())
        assert all(schema.incremental_fields == [] for schema in schemas.values())
        # Primary keys are surfaced so the public docs' Supported tables section renders them.
        assert all(schema.detected_primary_keys == ["id"] for schema in schemas.values())

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["workflows"])
        assert len(schemas) == 1
        assert schemas[0].name == "workflows"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.n8n.source.validate_n8n_credentials")
    @mock.patch.object(N8nSource, "is_database_host_valid")
    def test_validate_credentials_happy_path(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_host_valid.assert_called_once_with("myorg.app.n8n.cloud", self.team_id)
        mock_validate.assert_called_once_with("https://myorg.app.n8n.cloud", "key")

    @mock.patch.object(N8nSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Host is not allowed"

    def test_validate_credentials_rejects_invalid_url(self):
        config = N8nSourceConfig(host="ftp://nope", api_key="key")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid n8n instance URL"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.n8n.source.validate_n8n_credentials")
    @mock.patch.object(N8nSource, "is_database_host_valid")
    def test_validate_credentials_bad_key(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid n8n credentials" in (error_message or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.n8n.source.n8n_source")
    @mock.patch.object(N8nSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_n8n_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "workflows"
        inputs.team_id = self.team_id
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_n8n_source.assert_called_once()
        kwargs = mock_n8n_source.call_args.kwargs
        assert kwargs["host"] == "https://myorg.app.n8n.cloud"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "workflows"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch.object(N8nSource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "workflows"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
