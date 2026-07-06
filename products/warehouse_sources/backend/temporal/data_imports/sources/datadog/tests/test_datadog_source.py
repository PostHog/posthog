from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog import DatadogResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import (
    ENDPOINTS,
    LIMITED_RETENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source import DatadogSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DatadogSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"logs", "audit_logs", "events"}


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "logs",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestDatadogSource:
    def setup_method(self) -> None:
        self.source = DatadogSource()
        self.team_id = 123
        self.config = DatadogSourceConfig(api_key="dd-api", application_key="dd-app", site="datadoghq.com")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DATADOG

    def test_site_is_a_connection_host_field(self) -> None:
        # Changing the site must force the secrets to be re-entered so they're never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["site"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Datadog"
        assert config.label == "Datadog"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/datadog.svg"

        site_field, api_key_field, app_key_field = config.fields

        assert isinstance(site_field, SourceFieldSelectConfig)
        assert site_field.name == "site"
        assert site_field.required is True
        assert site_field.defaultValue == "datadoghq.com"
        assert {o.value for o in site_field.options} == {
            "datadoghq.com",
            "us3.datadoghq.com",
            "us5.datadoghq.com",
            "datadoghq.eu",
            "ap1.datadoghq.com",
            "ddog-gov.com",
        }

        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        assert isinstance(app_key_field, SourceFieldInputConfig)
        assert app_key_field.name == "application_key"
        assert app_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert app_key_field.required is True
        assert app_key_field.secret is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert schemas[name].incremental_fields == [
                {
                    "label": "timestamp",
                    "type": "datetime",
                    "field": "timestamp",
                    "field_type": "datetime",
                }
            ]

        for name in set(ENDPOINTS) - INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_retention_description(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name in LIMITED_RETENTION_ENDPOINTS:
            assert schemas[name].description is not None
        assert schemas["dashboards"].description is None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, None), True, None),
            ((False, "Invalid Datadog API key."), False, "Invalid Datadog API key."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source.validate_datadog_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("datadoghq.com", "dd-api", "dd-app")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DatadogResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source.datadog_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="monitors", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            site="datadoghq.com",
            api_key="dd-api",
            app_key="dd-app",
            endpoint="monitors",
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datadog.source.datadog_source")
    def test_source_for_pipeline_passes_incremental_value_when_enabled(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="timestamp",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
