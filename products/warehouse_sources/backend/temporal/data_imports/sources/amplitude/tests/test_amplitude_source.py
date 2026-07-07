from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.amplitude import AmplitudeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    ANNOTATIONS_ENDPOINT,
    COHORTS_ENDPOINT,
    ENDPOINTS,
    EVENTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source import AmplitudeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AmplitudeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

FULL_REFRESH_ENDPOINTS = [COHORTS_ENDPOINT, ANNOTATIONS_ENDPOINT]


class TestAmplitudeSource:
    def setup_method(self):
        self.source = AmplitudeSource()
        self.team_id = 123
        self.config = AmplitudeSourceConfig(api_key="key", secret_key="secret", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.AMPLITUDE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Amplitude"
        assert config.label == "Amplitude"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/amplitude.png"
        assert len(config.fields) == 3

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        secret_key_field = config.fields[1]
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert secret_key_field.name == "secret_key"
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.secret is True

        region_field = config.fields[2]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.name == "region"
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu"}

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error: Unauthorized", "403 Client Error: Forbidden", "Invalid API Key"],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_events_endpoint_advertises_incremental(self):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == EVENTS_ENDPOINT)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {field["field"] for field in schema.incremental_fields} == {"server_upload_time"}
        assert schema.description == "Only syncs the last 30 days on initial sync"

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[EVENTS_ENDPOINT])
        assert len(schemas) == 1
        assert schemas[0].name == EVENTS_ENDPOINT

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Amplitude rejected the credentials."), False, "Amplitude rejected the credentials."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source.validate_amplitude_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.secret_key, self.config.region)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AmplitudeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source.amplitude_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_amplitude_source):
        mock_amplitude_source.return_value = SimpleNamespace(name=EVENTS_ENDPOINT)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        logger = mock.MagicMock()
        inputs = SimpleNamespace(
            schema_name=EVENTS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-1",
            logger=logger,
            should_use_incremental_field=True,
            incremental_field="server_upload_time",
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_amplitude_source.assert_called_once_with(
            api_key="key",
            secret_key="secret",
            region="us",
            endpoint=EVENTS_ENDPOINT,
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        assert response is mock_amplitude_source.return_value

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source.amplitude_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_amplitude_source):
        mock_amplitude_source.return_value = SimpleNamespace(name=COHORTS_ENDPOINT)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(
            schema_name=COHORTS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-2",
            logger=mock.MagicMock(),
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        # When the user isn't running incrementally, no watermark should leak through.
        assert mock_amplitude_source.call_args.kwargs["db_incremental_field_last_value"] is None
