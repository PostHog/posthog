import pytest
from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gleif import GleifSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.gleif import GleifResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LEI_RECORDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source import GleifSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source.validate_gleif_credentials"
)
_SOURCE_FN_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source.gleif_source"


class TestGleifSource:
    def setup_method(self) -> None:
        self.source = GleifSource()
        self.team_id = 123
        self.config = GleifSourceConfig()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.GLEIF

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Gleif"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source must ship visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        # GLEIF is fully open and keyless, so the connect form has nothing to fill in.
        assert config.fields == []

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_lei_records_supports_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {LEI_RECORDS}
        assert schemas[LEI_RECORDS].incremental_fields == INCREMENTAL_FIELDS[LEI_RECORDS]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=[LEI_RECORDS])
        assert [schema.name for schema in schemas] == [LEI_RECORDS]

    @pytest.mark.parametrize(("mock_return", "expected_valid"), [(True, True), (False, False)])
    @mock.patch(_VALIDATE_PATCH)
    def test_validate_credentials(self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GleifResumeConfig

    @mock.patch(_SOURCE_FN_PATCH)
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = LEI_RECORDS
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-08-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == LEI_RECORDS
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-08-01T00:00:00Z"

    @mock.patch(_SOURCE_FN_PATCH)
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = LEI_RECORDS
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-08-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    def test_get_documented_tables_uses_canonical_descriptions(self) -> None:
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
        lei_records = next(table for table in tables if table["name"] == LEI_RECORDS)
        assert lei_records["description"]
        assert "Incremental" in lei_records["sync_methods"]
