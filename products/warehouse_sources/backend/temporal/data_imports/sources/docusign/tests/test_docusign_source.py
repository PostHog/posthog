from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.settings import (
    DOCUSIGN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.source import DocusignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.docusign import (
    DocusignAuthTypeConfig,
    DocusignSourceConfig,
)

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.docusign.source.validate_docusign_credentials"
)


def jwt_config(**overrides: Any) -> DocusignSourceConfig:
    auth_kwargs: dict[str, Any] = {
        "selection": "jwt",
        "integration_key": "int-key",
        "user_id": "user-guid",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----",
    }
    auth_kwargs.update(overrides.pop("auth", {}))
    return DocusignSourceConfig(
        auth_type=DocusignAuthTypeConfig(**auth_kwargs),
        environment=overrides.pop("environment", "production"),
        account_id=overrides.pop("account_id", None),
        start_date=overrides.pop("start_date", None),
    )


class TestDocusignSource:
    def setup_method(self) -> None:
        self.source = DocusignSource()
        self.team_id = 123

    def test_api_version_metadata_pins_what_the_transport_calls(self) -> None:
        assert self.source.supported_versions == ("v2.1",)
        assert self.source.default_version in self.source.supported_versions
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            primary_keys = DOCUSIGN_ENDPOINTS[name].primary_key
            assert set(primary_keys) <= set(entry.get("columns", {})), name

    @pytest.mark.parametrize(
        "auth_overrides,expected_fragment",
        [
            ({"private_key": None}, "RSA private key"),
            ({"user_id": None}, "impersonated user ID"),
            (
                {"selection": "refresh_token", "user_id": None, "private_key": None, "secret_key": "s"},
                "refresh token",
            ),
            (
                {"selection": "refresh_token", "user_id": None, "private_key": None, "refresh_token": "r"},
                "secret key",
            ),
        ],
    )
    def test_validate_credentials_rejects_a_half_filled_auth_option(
        self, auth_overrides: dict[str, Any], expected_fragment: str
    ) -> None:
        config = jwt_config(auth=auth_overrides)

        with mock.patch(_VALIDATE) as probe:
            valid, message = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        assert message is not None and expected_fragment in message
        # A half-filled form must not cost a DocuSign round trip.
        probe.assert_not_called()

    def test_validate_credentials_delegates_to_the_transport(self) -> None:
        with mock.patch(_VALIDATE, return_value=(True, None)) as probe:
            assert self.source.validate_credentials(jwt_config(account_id="222"), self.team_id) == (True, None)

        credentials = probe.call_args.args[0]
        assert credentials.environment == "production"
        assert credentials.selection == "jwt"
        assert credentials.integration_key == "int-key"
        assert credentials.account_id == "222"

    def test_validate_credentials_passes_the_transport_failure_through(self) -> None:
        with mock.patch(_VALIDATE, return_value=(False, "nope")):
            assert self.source.validate_credentials(jwt_config(), self.team_id) == (False, "nope")

    def test_optional_config_fields_default_to_none(self) -> None:
        config: Optional[DocusignSourceConfig] = jwt_config()

        assert config is not None
        assert config.account_id is None
        assert config.start_date is None
        assert config.environment == "production"
