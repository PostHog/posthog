import pytest
from unittest import mock
from unittest.mock import MagicMock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zero import ZeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.settings import ENDPOINT_CONFIGS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.source import ZeroSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero import ZeroResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {name for name, config in ENDPOINT_CONFIGS.items() if config.incremental_fields}


class TestZeroSource:
    def setup_method(self) -> None:
        self.source = ZeroSource()
        self.team_id = 123
        self.config = ZeroSourceConfig(api_key="api_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ZERO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Zero"
        assert config.label == "Zero"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/zero.png"
        assert config.category == DataWarehouseSourceCategory.CRM
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert len(schema.incremental_fields) >= 1
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Companies"])
        assert len(schemas) == 1
        assert schemas[0].name == "Companies"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zero.source.validate_zero_credentials"
    )
    def test_validate_credentials(self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("api_test")

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZeroResumeConfig

    def test_get_canonical_descriptions_covers_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zero.source.zero_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_zero_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Companies"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updatedAt"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_zero_source.assert_called_once_with(
            api_key="api_test",
            endpoint="Companies",
            team_id=7,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="updatedAt",
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zero.source.zero_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_zero_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Users"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_zero_source.call_args.kwargs["db_incremental_field_last_value"] is None
