import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source import CodecovSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codecov import (
    CodecovSourceConfig,
)


class TestCodecovSource:
    def setup_method(self):
        self.source = CodecovSource()
        self.team_id = 123
        self.config = CodecovSourceConfig(owner_username="acme", api_token="token")

    def test_connection_host_fields_force_secret_reentry_on_scope_change(self):
        # Retargeting the git provider, owner, or repository allow-list reuses the stored token
        # against different Codecov resources, so the update serializer must require re-entry.
        assert self.source.connection_host_fields == ["service", "owner_username", "repositories"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["commits"])
        assert [s.name for s in schemas] == ["commits"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Codecov API token"),
            ((False, 404), False, "Owner 'acme' not found on Codecov for the selected git provider"),
            ((False, None), False, "Could not connect to Codecov with the provided credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.codecov.source.validate_codecov_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
