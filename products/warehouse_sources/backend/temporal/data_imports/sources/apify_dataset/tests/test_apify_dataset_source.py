import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.apify_dataset import (
    ApifyResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.source import ApifyDatasetSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ApifyDatasetSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> ApifyDatasetSourceConfig:
    return ApifyDatasetSourceConfig(api_token="apify_api_token", dataset_id="ds1")


class TestApifyDatasetSource:
    def setup_method(self) -> None:
        self.source = ApifyDatasetSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.APIFYDATASET

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Apify Dataset"
        assert config.iconPath == "/static/services/apify_dataset.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/apify-dataset"
        # Not hidden — a finished source ships visible, gated only by its alpha release status.
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == "alpha"

    def test_source_config_fields(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_token", "dataset_id"}
        api_token, dataset_id = fields["api_token"], fields["dataset_id"]
        assert isinstance(api_token, SourceFieldInputConfig)
        assert isinstance(dataset_id, SourceFieldInputConfig)
        assert api_token.required and api_token.secret
        assert dataset_id.required and not dataset_id.secret

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_includes_dataset_id(self) -> None:
        # dataset_id targets the stored token, so changing it must force re-entry of the secret.
        assert self.source.connection_host_fields == ["dataset_id"]

    def test_get_schemas_is_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(_config(), self.team_id)
        assert [s.name for s in schemas] == ["dataset_items"]
        schema = schemas[0]
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []
        assert schema.detected_primary_keys is None

    def test_get_schemas_filters_by_names(self) -> None:
        assert self.source.get_schemas(_config(), self.team_id, names=["nope"]) == []
        assert [s.name for s in self.source.get_schemas(_config(), self.team_id, names=["dataset_items"])] == [
            "dataset_items"
        ]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert len(tables) == 1
        assert tables[0]["name"] == "dataset_items"
        assert tables[0]["sync_methods"] == ["Full refresh"]

    @pytest.mark.parametrize("status", ["401", "403", "404"])
    def test_non_retryable_errors_cover_auth_and_addressing(self, status: str) -> None:
        keys = self.source.get_non_retryable_errors()
        assert any(status in key for key in keys)

    def test_validate_credentials_delegates_to_transport(self) -> None:
        with mock.patch.object(source_module, "validate_apify_credentials", return_value=(True, None)) as validate:
            ok, error = self.source.validate_credentials(_config(), self.team_id)
        assert ok is True and error is None
        validate.assert_called_once_with("apify_api_token", "ds1")

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        inputs = mock.Mock()
        inputs.logger = mock.Mock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ApifyResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = mock.Mock()
        inputs.schema_name = "dataset_items"
        inputs.logger = mock.Mock()
        manager = mock.Mock()
        with mock.patch.object(source_module, "apify_dataset_source", return_value="sentinel") as build:
            result = self.source.source_for_pipeline(_config(), manager, inputs)
        assert result is build.return_value
        build.assert_called_once_with(
            api_token="apify_api_token",
            dataset_id="ds1",
            endpoint="dataset_items",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
