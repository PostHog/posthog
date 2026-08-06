from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sprig import SprigSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source import SprigSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig import SprigResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> SprigSourceConfig:
    return SprigSourceConfig(api_key="sprig-key")


class TestSprigSourceConfig:
    def test_source_type(self) -> None:
        assert SprigSource().source_type == ExternalDataSourceType.SPRIG

    def test_get_source_config(self) -> None:
        config = SprigSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.SPRIG
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None

    def test_single_secret_api_key_field(self) -> None:
        fields = SprigSource().get_source_config.fields
        assert fields is not None
        assert len(fields) == 1
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True


class TestGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = SprigSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(list(ENDPOINTS))
    def test_incremental_support_matches_settings(self, endpoint: str) -> None:
        schema = next(s for s in SprigSource().get_schemas(_config(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]

    def test_names_filter(self) -> None:
        schemas = SprigSource().get_schemas(_config(), team_id=1, names=["Surveys"])
        assert {s.name for s in schemas} == {"Surveys"}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source.validate_sprig_credentials")
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = SprigSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestSourceWiring:
    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = SprigSource().get_non_retryable_errors()
        keys = " ".join(errors.keys())
        assert "401" in keys
        assert "403" in keys

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = SprigSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SprigResumeConfig

    def test_canonical_descriptions_present(self) -> None:
        descriptions = SprigSource().get_canonical_descriptions()
        assert "Surveys" in descriptions
        assert "Responses" in descriptions
        assert set(descriptions.keys()).issubset(set(ENDPOINTS))

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source.sprig_source")
    def test_source_for_pipeline_plumbing(self, mock_sprig_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Responses"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"

        SprigSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = cast(dict[str, Any], mock_sprig_source.call_args.kwargs)
        assert kwargs["api_key"] == "sprig-key"
        assert kwargs["endpoint"] == "Responses"
        assert kwargs["team_id"] == 7
        assert kwargs["job_id"] == "job-1"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"
        assert kwargs["resumable_source_manager"] is manager

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source.sprig_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_sprig_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "Surveys"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"

        SprigSource().source_for_pipeline(_config(), MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_sprig_source.call_args.kwargs["db_incremental_field_last_value"] is None
