from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RecurlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.recurly import RecurlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.settings import (
    ENDPOINTS,
    RECURLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source import RecurlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if e.supports_incremental]
FULL_REFRESH_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if not e.supports_incremental]


class TestRecurlySource:
    def setup_method(self):
        self.source = RecurlySource()
        self.team_id = 123
        self.config = RecurlySourceConfig(api_key="test-key", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.RECURLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Recurly"
        assert config.label == "Recurly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/recurly.png"
        assert len(config.fields) == 2

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        region_field = config.fields[1]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.name == "region"
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu"}

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {field["field"] for field in schema.incremental_fields} == {"created_at", "updated_at"}

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["accounts"])
        assert len(schemas) == 1
        assert schemas[0].name == "accounts"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Recurly rejected the API key."), False, "Recurly rejected the API key."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source.validate_recurly_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RecurlyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source.recurly_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_recurly_source):
        mock_recurly_source.return_value = SimpleNamespace(name="accounts", column_hints=None)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(
            schema_name="accounts",
            team_id=self.team_id,
            job_id="job-1",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_recurly_source.assert_called_once_with(
            api_key="test-key",
            region="us",
            endpoint="accounts",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        assert response.name == "accounts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.sort_mode == "asc"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source.recurly_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_recurly_source):
        mock_recurly_source.return_value = SimpleNamespace(name="plans", column_hints=None)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(
            schema_name="plans",
            team_id=self.team_id,
            job_id="job-2",
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        # When the user isn't running incrementally, no watermark should leak through.
        assert mock_recurly_source.call_args.kwargs["db_incremental_field_last_value"] is None
