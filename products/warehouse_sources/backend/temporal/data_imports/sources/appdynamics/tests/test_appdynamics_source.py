import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.appdynamics import AppdynamicsAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.settings import (
    ENDPOINTS,
    MAX_METRIC_PATHS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.source import AppdynamicsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appdynamics import (
    AppdynamicsAuthMethodConfig,
    AppdynamicsSourceConfig,
)


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


class TestAppdynamicsSource:
    def setup_method(self) -> None:
        self.source = AppdynamicsSource()
        self.team_id = 1

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_api_client_config(), self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        incremental_endpoints = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental_endpoints == {"health_rule_violations", "metric_data"}
        for name in incremental_endpoints:
            assert {f["field"] for f in schemas[name].incremental_fields} == {"startTimeInMillis"}

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
