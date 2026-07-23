from typing import Optional

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recreation import (
    RecreationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.recreation import (
    RecreationResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import RECREATION_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.source import RecreationSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _source_inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestRecreationSource:
    def setup_method(self) -> None:
        self.source = RecreationSource()
        self.config = RecreationSourceConfig(api_key="test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.RECREATION

    def test_source_is_released_with_alpha_status(self) -> None:
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_api_key_field_is_secret_password(self) -> None:
        fields = self.source.get_source_config.fields
        assert [f.name for f in fields] == ["api_key"]
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.secret is True
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True

    def test_get_schemas_returns_full_refresh_only_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert {s.name for s in schemas} == set(RECREATION_ENDPOINTS.keys())
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["Facilities", "Campsites"])
        assert {s.name for s in schemas} == {"Facilities", "Campsites"}

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_error_fragment"),
        [
            (200, True, None),
            (401, False, "Invalid RIDB API key"),
            (403, False, "Invalid RIDB API key"),
            (500, False, "unexpected response"),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_error_fragment: Optional[str]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.recreation.recreation.make_tracked_session"
        ) as mock_session_factory:
            mock_session_factory.return_value.get.return_value.status_code = status_code
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("Facilities"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RecreationResumeConfig

    @pytest.mark.parametrize("endpoint", list(RECREATION_ENDPOINTS.keys()))
    def test_source_for_pipeline_maps_endpoint_to_response(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        response = self.source.source_for_pipeline(self.config, manager, _source_inputs(endpoint))

        endpoint_config = RECREATION_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [endpoint_config.primary_key]
        if endpoint_config.partition_key is not None:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [endpoint_config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
