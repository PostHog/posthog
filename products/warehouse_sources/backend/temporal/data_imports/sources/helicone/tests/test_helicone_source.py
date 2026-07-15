from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HeliconeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.helicone import HeliconeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.settings import (
    ENDPOINTS,
    PROMPTS_ENDPOINT,
    REQUESTS_ENDPOINT,
    SESSIONS_ENDPOINT,
    USERS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source import HeliconeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

FULL_REFRESH_ENDPOINTS = [SESSIONS_ENDPOINT, USERS_ENDPOINT, PROMPTS_ENDPOINT]


class TestHeliconeSource:
    def setup_method(self):
        self.source = HeliconeSource()
        self.team_id = 123
        self.config = HeliconeSourceConfig(api_key="sk-helicone-key", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.HELICONE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Helicone"
        assert config.label == "Helicone"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/helicone.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/helicone"
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

    @pytest.mark.parametrize("status_text", ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"])
    @pytest.mark.parametrize("host", ["https://api.helicone.ai", "https://eu.api.helicone.ai"])
    def test_non_retryable_errors_cover_both_regional_hosts(self, status_text, host):
        assert f"{status_text} for url: {host}" in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_requests_endpoint_advertises_incremental(self):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == REQUESTS_ENDPOINT)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {field["field"] for field in schema.incremental_fields} == {"request_created_at"}

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[REQUESTS_ENDPOINT])
        assert [schema.name for schema in schemas] == [REQUESTS_ENDPOINT]

    @pytest.mark.parametrize(
        "mock_return",
        [(True, None), (False, "Helicone rejected the API key.")],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source.validate_helicone_credentials"
    )
    def test_validate_credentials_plumbs_transport_result(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HeliconeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source.helicone_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_helicone_source):
        mock_helicone_source.return_value = SimpleNamespace(name=REQUESTS_ENDPOINT)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        logger = mock.MagicMock()
        inputs = SimpleNamespace(
            schema_name=REQUESTS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-1",
            logger=logger,
            should_use_incremental_field=True,
            incremental_field="request_created_at",
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_helicone_source.assert_called_once_with(
            api_key="sk-helicone-key",
            region="us",
            endpoint=REQUESTS_ENDPOINT,
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="request_created_at",
        )
        assert response is mock_helicone_source.return_value

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source.helicone_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_helicone_source):
        mock_helicone_source.return_value = SimpleNamespace(name=SESSIONS_ENDPOINT)
        inputs = SimpleNamespace(
            schema_name=SESSIONS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-2",
            logger=mock.MagicMock(),
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        self.source.source_for_pipeline(
            self.config, mock.MagicMock(spec=ResumableSourceManager), cast(SourceInputs, inputs)
        )

        # When the user isn't running incrementally, no watermark should leak through.
        assert mock_helicone_source.call_args.kwargs["db_incremental_field_last_value"] is None
