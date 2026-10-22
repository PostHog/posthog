from base64 import b64encode

import pytest

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imagga import ImaggaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source import ImaggaSource


class TestImaggaSource:
    def setup_method(self) -> None:
        self.source = ImaggaSource()
        self.team_id = 123
        self.config = ImaggaSourceConfig(api_key="acc_test", api_secret="secret_test")

    def test_api_secret_is_a_secret_password_field(self) -> None:
        # The secret must never render as plain text or be treated as non-sensitive by the serializer.
        field = next(f for f in self.source.get_source_config.fields if f.name == "api_secret")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe to surface in public docs.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "status,expected_valid",
        [(200, True)],
    )
    def test_validate_credentials(self, status: int, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        assert [request.path for request in network.requests_log] == ["/v2/usage"]
        assert (
            network.requests_log[0].headers["authorization"] == "Basic " + b64encode(b"acc_test:secret_test").decode()
        )
