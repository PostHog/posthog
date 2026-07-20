import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HyperspellSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HyperspellResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source import HyperspellSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source"


def _make_inputs(schema_name: str = "memories") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestHyperspellSource:
    def setup_method(self):
        self.source = HyperspellSource()
        self.team_id = 123
        self.config = HyperspellSourceConfig(api_key="hs_test", region="eu", user_ids="user-1, user-2")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HYPERSPELL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Hyperspell"
        assert config.label == "Hyperspell"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/hyperspell.svg"
        assert [f.name for f in config.fields] == ["api_key", "region", "user_ids"]

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        region_field = config.fields[1]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us"
        assert [option.value for option in region_field.options] == ["us", "eu"]

        user_ids_field = config.fields[2]
        assert isinstance(user_ids_field, SourceFieldInputConfig)
        assert user_ids_field.required is False

    def test_get_schemas_lists_all_endpoints_as_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Hyperspell endpoint has a server-side timestamp filter, so nothing may
        # advertise incremental support.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["memories", "nonexistent"])

        assert [schema.name for schema in schemas] == ["memories"]

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized",
            "403 Client Error: Forbidden",
        ],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    @mock.patch(f"{MODULE}.validate_hyperspell_credentials")
    def test_validate_credentials_passes_region(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "memories")

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with("hs_test", "eu", "memories")

    def test_get_resumable_source_manager(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HyperspellResumeConfig

    @mock.patch(f"{MODULE}.hyperspell_source")
    def test_source_for_pipeline_plumbs_config(self, mock_hyperspell_source):
        manager = mock.MagicMock()
        inputs = _make_inputs(schema_name="connections")

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_hyperspell_source.assert_called_once_with(
            api_key="hs_test",
            region="eu",
            user_ids="user-1, user-2",
            endpoint="connections",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
