import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.servicenow import (
    ServiceNowAuthMethodConfig,
    ServiceNowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.servicenow import (
    SERVICENOW_API_VERSION_V1,
    SERVICENOW_API_VERSION_V2,
    ServiceNowAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source import ServiceNowSource


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


class TestServiceNowSource:
    def setup_method(self) -> None:
        self.source = ServiceNowSource()
        self.team_id = 1

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

    def test_default_version_is_v2(self) -> None:
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"


class TestValidateCredentialsResolvedPin:
    @parameterized.expand(
        [
            (SERVICENOW_API_VERSION_V1, SERVICENOW_API_VERSION_V1),
            (SERVICENOW_API_VERSION_V2, SERVICENOW_API_VERSION_V2),
            # No pin (pre-creation) resolves to the default the new row is stamped with.
            (None, ServiceNowSource.default_version),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source.validate_servicenow_credentials"
    )
    def test_probe_receives_resolved_pin(self, pin, expected, mock_validate: mock.Mock) -> None:
        # The probe hits the versioned Table API path, so a v1-pinned source must validate
        # against /api/now/table while the (v2) default validates against /api/now/v2/table.
        mock_validate.return_value = (True, None)
        ServiceNowSource().validate_credentials(_api_key_config(), 1, api_version=pin)

        _, kwargs = mock_validate.call_args
        assert kwargs["api_version"] == expected
