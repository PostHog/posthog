import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stytch import StytchSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source import StytchSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.stytch import StytchAPIError, get_rows


class TestStytchSource:
    def setup_method(self):
        self.source = StytchSource()
        self.team_id = 123
        self.config = StytchSourceConfig(project_id="project-live-x", secret="secret-live-x")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Stytch API error: status=400, error_type=invalid_project_id_authentication, url=https://api.stytch.com/v1/users/search",
            "Stytch API error: status=401, error_type=unauthorized_credentials, url=https://test.stytch.com/v1/users/search",
            "Stytch API error: status=401, error_type=invalid_secret_authentication, url=https://api.stytch.com/v1/sessions",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "transient_error",
        [
            "Stytch API error (retryable): status=429, url=https://api.stytch.com/v1/users/search",
            "Stytch API error: status=400, error_type=query_params_invalid, url=https://api.stytch.com/v1/users/search",
            "Stytch API error (retryable): status=400, error_type=search_timeout, url=https://api.stytch.com/v1/b2b/organizations/search",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient_or_query_errors(self, transient_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in transient_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "endpoint, error_type, advised_tables",
        [
            ("users", "invalid_consumer_endpoint", "organizations and members"),
            ("sessions", "invalid_consumer_endpoint", "organizations and members"),
            ("organizations", "invalid_b2b_endpoint", "users and sessions"),
            ("members", "invalid_b2b_endpoint", "users and sessions"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.stytch.stytch.make_tracked_session")
    def test_product_line_mismatch_is_classified_with_the_tables_to_use_instead(
        self, mock_session, endpoint, error_type, advised_tables
    ):
        # Drive the real transport so the raised message and the classifier's patterns cannot drift
        # apart: an unclassified failure leaves the schema enabled and retrying a request Stytch
        # will always reject.
        response = mock.MagicMock(status_code=400, ok=False)
        response.json.return_value = {"error_type": error_type}
        mock_session.return_value.request.return_value = response
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        with pytest.raises(StytchAPIError) as raised:
            list(get_rows(self.config.project_id, self.config.secret, endpoint, mock.MagicMock(), manager))

        classified = [
            message
            for pattern, message in self.source.get_non_retryable_errors().items()
            if error_message_matches(str(raised.value), [pattern])
        ]
        assert len(classified) == 1
        assert advised_tables in (classified[0] or "")
        assert mock_session.return_value.request.call_count == 1

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the users search exposes a server-side timestamp filter (created_at_greater_than).
        assert incremental == {"users"}

    def test_expensive_and_b2b_tables_are_off_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["users"].should_sync_default is True
        assert schemas["sessions"].should_sync_default is False
        assert schemas["organizations"].should_sync_default is False
        assert schemas["members"].should_sync_default is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert [schema.name for schema in schemas] == ["users"]

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
