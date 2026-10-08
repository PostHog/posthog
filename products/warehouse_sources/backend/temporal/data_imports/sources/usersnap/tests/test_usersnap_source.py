import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.usersnap import (
    UsersnapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.source import UsersnapSource


class TestUsersnapSource:
    def setup_method(self):
        self.source = UsersnapSource()
        self.team_id = 123
        self.config = UsersnapSourceConfig(jwt_secret="shared-secret", jwt_id="jwt-id-123")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["feedbacks"])
        assert len(schemas) == 1
        assert schemas[0].name == "feedbacks"

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.usersnap.source.validate_usersnap_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with(self.config.jwt_secret, self.config.jwt_id)
