import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.appdynamics import (
    AppdynamicsAuth,
    AppdynamicsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.settings import (
    ENDPOINTS,
    MAX_METRIC_PATHS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.source import AppdynamicsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    AppdynamicsAuthMethodConfig,
    AppdynamicsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _api_client_config(metric_paths: str | None = None) -> AppdynamicsSourceConfig:
    return AppdynamicsSourceConfig(
        host="https://acme.saas.appdynamics.com",
        account_name="acme",
        auth_method=AppdynamicsAuthMethodConfig(
            selection="api_client", api_client_name="client", api_client_secret="secret"
        ),
        metric_paths=metric_paths,
    )


def _basic_config(username: str | None = "user", password: str | None = "pass") -> AppdynamicsSourceConfig:
    return AppdynamicsSourceConfig(
        host="https://acme.saas.appdynamics.com",
        account_name="acme",
        auth_method=AppdynamicsAuthMethodConfig(selection="basic", username=username, password=password),
    )


def _source_inputs(schema_name: str = "applications", incremental: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=1704067200000 if incremental else None,
        db_incremental_field_earliest_value=None,
        incremental_field="startTimeInMillis" if incremental else None,
        incremental_field_type=None,
        job_id="job-1",
        logger=mock.MagicMock(),
        reset_pipeline=False,
    )


class TestAppdynamicsSource:
    def setup_method(self) -> None:
        self.source = AppdynamicsSource()
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.APPDYNAMICS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Appdynamics"
        assert config.unreleasedSource is not True
        assert config.releaseStatus == ReleaseStatus.ALPHA

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "account_name", "auth_method", "metric_paths"]

        host_field = config.fields[0]
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.required is True

        auth_field = config.fields[2]
        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert {option.value for option in auth_field.options} == {"api_client", "basic"}

    def test_non_retryable_errors(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors
        assert "AppDynamics OAuth token request failed" in errors

    def test_account_name_is_a_connection_host_field(self) -> None:
        # Changing account_name retargets the preserved credential, so it must force re-entry.
        assert self.source.connection_host_fields == ["account_name"]

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_api_client_config(), self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        incremental_endpoints = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental_endpoints == {"health_rule_violations", "metric_data"}
        for name in incremental_endpoints:
            assert {f["field"] for f in schemas[name].incremental_fields} == {"startTimeInMillis"}

    def test_get_schemas_filtered_by_name(self) -> None:
        schemas = self.source.get_schemas(_api_client_config(), self.team_id, names=["applications"])
        assert [s.name for s in schemas] == ["applications"]
        assert self.source.get_schemas(_api_client_config(), self.team_id, names=["nope"]) == []

    def test_auth_for_config_api_client(self) -> None:
        auth = self.source._auth_for_config(_api_client_config())
        assert auth == AppdynamicsAuth(account_name="acme", api_client_name="client", api_client_secret="secret")
        assert auth.uses_oauth is True

    def test_auth_for_config_basic(self) -> None:
        auth = self.source._auth_for_config(_basic_config("u", "p"))
        assert auth == AppdynamicsAuth(account_name="acme", username="u", password="p")
        assert auth.uses_oauth is False

    def test_auth_for_config_missing_basic_password_raises(self) -> None:
        with pytest.raises(ValueError):
            self.source._auth_for_config(_basic_config("u", None))

    def test_auth_for_config_missing_api_client_secret_raises(self) -> None:
        config = AppdynamicsSourceConfig(
            host="https://acme.saas.appdynamics.com",
            account_name="acme",
            auth_method=AppdynamicsAuthMethodConfig(selection="api_client", api_client_name="client"),
        )
        with pytest.raises(ValueError):
            self.source._auth_for_config(config)

    def test_metric_paths_default_when_empty(self) -> None:
        assert self.source._metric_paths_for_config(_api_client_config()) == ["Overall Application Performance|*"]

    def test_metric_paths_parsed_from_textarea(self) -> None:
        config = _api_client_config(
            metric_paths="Overall Application Performance|*\n\n  Business Transaction Performance|*|*  \n"
        )
        assert self.source._metric_paths_for_config(config) == [
            "Overall Application Performance|*",
            "Business Transaction Performance|*|*",
        ]

    def test_metric_paths_over_limit_rejected(self) -> None:
        config = _api_client_config(metric_paths="\n".join(f"Metric|{i}" for i in range(MAX_METRIC_PATHS + 1)))

        with pytest.raises(ValueError):
            self.source._metric_paths_for_config(config)

        # the same cap rejects the config at source create/edit time
        valid, error = self.source.validate_credentials(config, self.team_id)
        assert valid is False
        assert error is not None and "Too many metric paths" in error

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.source.validate_appdynamics_credentials"
    )
    def test_validate_credentials_plumbing(self, mock_validate: mock.Mock) -> None:
        mock_validate.return_value = (True, None)
        valid, error = self.source.validate_credentials(_api_client_config(), self.team_id, schema_name="applications")

        assert (valid, error) == (True, None)
        _, kwargs = mock_validate.call_args
        assert kwargs["schema_name"] == "applications"

    def test_validate_credentials_missing_creds(self) -> None:
        valid, error = self.source.validate_credentials(_basic_config("u", None), self.team_id)
        assert valid is False
        assert error is not None

    def test_get_resumable_source_manager(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppdynamicsResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.source.appdynamics_source"
    )
    def test_source_for_pipeline_plumbing(self, mock_source: mock.Mock) -> None:
        inputs = _source_inputs(schema_name="health_rule_violations", incremental=True)
        manager = mock.MagicMock()

        self.source.source_for_pipeline(_api_client_config(), manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["host"] == "https://acme.saas.appdynamics.com"
        assert kwargs["auth"] == AppdynamicsAuth(
            account_name="acme", api_client_name="client", api_client_secret="secret"
        )
        assert kwargs["endpoint"] == "health_rule_violations"
        assert kwargs["team_id"] == 1
        assert kwargs["metric_paths"] == ["Overall Application Performance|*"]
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1704067200000

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.source.appdynamics_source"
    )
    def test_source_for_pipeline_full_refresh_drops_watermark(self, mock_source: mock.Mock) -> None:
        inputs = _source_inputs(schema_name="health_rule_violations", incremental=False)
        inputs.db_incremental_field_last_value = 1704067200000

        self.source.source_for_pipeline(_api_client_config(), mock.MagicMock(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
