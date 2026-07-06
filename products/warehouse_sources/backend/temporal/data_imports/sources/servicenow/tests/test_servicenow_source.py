import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ServiceNowAuthMethodConfig,
    ServiceNowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.servicenow import (
    ServiceNowAuth,
    ServiceNowResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source import ServiceNowSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _basic_config(username: str = "admin", password: str = "secret") -> ServiceNowSourceConfig:
    return ServiceNowSourceConfig(
        instance_url="https://acme.service-now.com",
        auth_method=ServiceNowAuthMethodConfig(selection="basic", username=username, password=password),
    )


def _api_key_config(api_key: str = "key123") -> ServiceNowSourceConfig:
    return ServiceNowSourceConfig(
        instance_url="https://acme.service-now.com",
        auth_method=ServiceNowAuthMethodConfig(selection="api_key", api_key=api_key),
    )


def _source_inputs(schema_name: str = "incidents", incremental: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2024-01-01 00:00:00" if incremental else None,
        db_incremental_field_earliest_value=None,
        incremental_field="sys_updated_on" if incremental else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=mock.MagicMock(),
        reset_pipeline=False,
    )


class TestServiceNowSource:
    def setup_method(self) -> None:
        self.source = ServiceNowSource()
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SERVICENOW

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "ServiceNow"
        assert config.label == "ServiceNow"
        assert config.unreleasedSource is not True
        assert config.releaseStatus == ReleaseStatus.ALPHA

        field_names = [f.name for f in config.fields]
        assert field_names == ["instance_url", "auth_method"]

        instance_field = config.fields[0]
        assert isinstance(instance_field, SourceFieldInputConfig)
        assert instance_field.required is True

        auth_field = config.fields[1]
        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert {option.value for option in auth_field.options} == {"basic", "api_key"}

    def test_non_retryable_errors(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors

    def test_get_schemas_all_incremental(self) -> None:
        schemas = self.source.get_schemas(_api_key_config(), self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental for s in schemas)
        assert all(s.supports_append for s in schemas)
        # both audit timestamps are advertised as incremental options
        assert all({f["field"] for f in s.incremental_fields} == {"sys_updated_on", "sys_created_on"} for s in schemas)

    def test_get_schemas_filtered_by_name(self) -> None:
        schemas = self.source.get_schemas(_api_key_config(), self.team_id, names=["incidents"])
        assert len(schemas) == 1
        assert schemas[0].name == "incidents"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(_api_key_config(), self.team_id, names=["nope"]) == []

    def test_auth_for_config_api_key(self) -> None:
        auth = self.source._auth_for_config(_api_key_config("abc"))
        assert auth == ServiceNowAuth(api_key="abc")

    def test_auth_for_config_basic(self) -> None:
        auth = self.source._auth_for_config(_basic_config("u", "p"))
        assert auth == ServiceNowAuth(username="u", password="p")

    def test_auth_for_config_missing_api_key_raises(self) -> None:
        config = ServiceNowSourceConfig(
            instance_url="https://acme.service-now.com",
            auth_method=ServiceNowAuthMethodConfig(selection="api_key"),
        )
        with pytest.raises(ValueError):
            self.source._auth_for_config(config)

    def test_auth_for_config_missing_basic_raises(self) -> None:
        config = ServiceNowSourceConfig(
            instance_url="https://acme.service-now.com",
            auth_method=ServiceNowAuthMethodConfig(selection="basic", username="only-user"),
        )
        with pytest.raises(ValueError):
            self.source._auth_for_config(config)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source.validate_servicenow_credentials"
    )
    def test_validate_credentials_success(self, mock_validate: mock.Mock) -> None:
        mock_validate.return_value = (True, None)
        valid, error = self.source.validate_credentials(_api_key_config(), self.team_id)
        assert valid is True
        assert error is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source.validate_servicenow_credentials"
    )
    def test_validate_credentials_maps_schema_to_table(self, mock_validate: mock.Mock) -> None:
        mock_validate.return_value = (True, None)
        self.source.validate_credentials(_api_key_config(), self.team_id, schema_name="incidents")

        _, kwargs = mock_validate.call_args
        assert kwargs["table"] == "incident"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source.validate_servicenow_credentials"
    )
    def test_validate_credentials_no_schema_passes_none_table(self, mock_validate: mock.Mock) -> None:
        mock_validate.return_value = (True, None)
        self.source.validate_credentials(_basic_config(), self.team_id)

        _, kwargs = mock_validate.call_args
        assert kwargs["table"] is None

    def test_validate_credentials_missing_creds(self) -> None:
        config = ServiceNowSourceConfig(
            instance_url="https://acme.service-now.com",
            auth_method=ServiceNowAuthMethodConfig(selection="api_key"),
        )
        valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert error is not None

    def test_get_resumable_source_manager(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ServiceNowResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source.servicenow_source")
    def test_source_for_pipeline_plumbing(self, mock_source: mock.Mock) -> None:
        config = _api_key_config("abc")
        inputs = _source_inputs(schema_name="problems", incremental=True)
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["instance_url"] == "https://acme.service-now.com"
        assert kwargs["auth"] == ServiceNowAuth(api_key="abc")
        assert kwargs["endpoint"] == "problems"
        assert kwargs["team_id"] == 1
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01 00:00:00"
        assert kwargs["incremental_field"] == "sys_updated_on"
