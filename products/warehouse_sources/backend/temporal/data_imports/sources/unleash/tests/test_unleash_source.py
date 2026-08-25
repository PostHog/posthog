import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.unleash import (
    UnleashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.source import UnleashSource


class TestUnleashSource:
    def setup_method(self) -> None:
        self.source = UnleashSource()
        self.team_id = 123
        self.config = UnleashSourceConfig(instance_url="https://unleash.example.com", api_token="user:secret-token")

    def test_connection_host_fields_covers_instance_url(self) -> None:
        # The stored API token is sent to whatever `instance_url` points at, so retargeting the
        # URL must force the editor to re-enter the token.
        assert self.source.connection_host_fields == ["instance_url"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["features"])
        assert len(schemas) == 1
        assert schemas[0].name == "features"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://unleash.example.com/api/admin/projects",),
            ("403 Client Error: Forbidden for url: https://unleash.example.com/api/admin/user-admin",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://unleash.example.com/api/admin/projects",),
            ("429 Client Error: Too Many Requests for url: https://unleash.example.com/api/admin/segments",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.unleash.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates_to_shared_helper(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"users": "needs admin", "features": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["users", "features"])
        assert result == {"users": "needs admin", "features": None}
        mock_check.assert_called_once_with(
            "https://unleash.example.com", "user:secret-token", ["users", "features"], self.team_id
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.unleash.source.unleash_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "features"
        inputs.team_id = self.team_id
        inputs.job_id = "job-123"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["instance_url"] == "https://unleash.example.com"
        assert kwargs["api_token"] == "user:secret-token"
        assert kwargs["endpoint"] == "features"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-123"
        assert kwargs["resumable_source_manager"] is manager
        assert "logger" not in kwargs

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Unleash schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
