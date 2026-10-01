import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import ReleaseStatus, SourceFieldInputConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.settings import (
    ENDPOINTS,
    TIMESERIES_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source import DatahubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datahub import (
    DatahubSourceConfig,
)


class TestDatahubSource:
    def setup_method(self) -> None:
        self.source = DatahubSource()
        self.team_id = 123
        self.config = DatahubSourceConfig(instance_url="https://datahub.example.com", api_token="secret-token")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Datahub"
        assert config.label == "DataHub"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/datahub"
        # A finished source must be visible in the wizard — the scaffold-era hidden flag stays out.
        assert not config.unreleasedSource

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["instance_url", "api_token"]

    def test_connection_host_fields_covers_instance_url(self) -> None:
        # The stored access token is sent to whatever `instance_url` points at, so retargeting
        # the URL must force the editor to re-enter the token.
        assert self.source.connection_host_fields == ["instance_url"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_marks_only_timeseries_endpoints_incremental(self) -> None:
        # Entity endpoints have no server-side updated-since filter, so a cursor offered on one
        # would silently re-read everything each sync while claiming to be incremental.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            is_timeseries = name in TIMESERIES_ENDPOINTS
            assert schema.supports_incremental is is_timeseries
            assert [f["field"] for f in schema.incremental_fields] == (["timestampMillis"] if is_timeseries else [])
            # Merge only: the startTimeMillis bound is inclusive, so an append would land the
            # boundary event again on every sync.
            assert schema.supports_append is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["datasets"])
        assert len(schemas) == 1
        assert schemas[0].name == "datasets"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_every_table_is_documented(self) -> None:
        # The public docs render this catalog, and a table with no entry falls back to an LLM
        # guess at its columns.
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://datahub.example.com/openapi/v3/entity/dataset",),
            ("403 Client Error: Forbidden for url: https://datahub.example.com/openapi/v3/entity/corpuser",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://datahub.example.com/openapi/v3/entity/dataset",),
            ("429 Client Error: Too Many Requests for url: https://datahub.example.com/openapi/v3/entity/tag",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates_to_shared_helper(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"users": "needs view privilege", "datasets": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["users", "datasets"])
        assert result == {"users": "needs view privilege", "datasets": None}
        mock_check.assert_called_once_with(
            "https://datahub.example.com", "secret-token", ["users", "datasets"], self.team_id
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.datahub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "datasets"
        inputs.team_id = self.team_id
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["instance_url"] == "https://datahub.example.com"
        assert kwargs["api_token"] == "secret-token"
        assert kwargs["endpoint"] == "datasets"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["resumable_source_manager"] is manager

    @parameterized.expand([(True, 1500), (False, None)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.datahub_source")
    def test_source_for_pipeline_only_passes_the_watermark_on_an_incremental_run(
        self, should_use_incremental_field: bool, expected: int | None, mock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "dataset_profiles"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = 1500

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] == expected

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown DataHub schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
