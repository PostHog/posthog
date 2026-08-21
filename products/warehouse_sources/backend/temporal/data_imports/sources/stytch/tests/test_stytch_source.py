import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stytch import StytchSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source import StytchSource


class TestStytchSource:
    def setup_method(self):
        self.source = StytchSource()
        self.team_id = 123
        self.config = StytchSourceConfig(project_id="project-live-x", secret="secret-live-x")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the users search exposes a server-side timestamp filter (created_at_greater_than).
        assert incremental == {"users"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Stytch project ID or secret"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source.validate_stytch_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.project_id, self.config.secret)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source.check_endpoint_access")
    def test_endpoint_permissions_probe_each_surface_once(self, mock_check):
        # A consumer (B2C) project: the B2B surface denies, the consumer surface is fine.
        mock_check.side_effect = lambda project_id, secret, path: (
            "Not available for this Stytch project (organization_not_found)" if "/b2b/" in path else None
        )

        permissions = self.source.get_endpoint_permissions(
            self.config, self.team_id, ["users", "sessions", "organizations", "members"]
        )

        assert permissions["users"] is None
        assert permissions["sessions"] is None
        assert permissions["organizations"] is not None
        assert permissions["members"] is not None
        # One probe per surface, not per endpoint.
        assert mock_check.call_count == 2
