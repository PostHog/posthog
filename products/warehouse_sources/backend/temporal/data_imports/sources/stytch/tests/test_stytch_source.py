import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StytchSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source import StytchSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stytch.stytch import StytchResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestStytchSource:
    def setup_method(self):
        self.source = StytchSource()
        self.team_id = 123
        self.config = StytchSourceConfig(project_id="project-live-x", secret="secret-live-x")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.STYTCH

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Stytch"
        assert config.label == "Stytch"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/stytch.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["project_id", "secret"]

    def test_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "secret")
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

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
        ],
    )
    def test_non_retryable_errors_do_not_match_transient_or_query_errors(self, transient_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in transient_error for key in non_retryable_errors)

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

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is StytchResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source.stytch_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_stytch_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_stytch_source.call_args.kwargs
        assert kwargs["project_id"] == "project-live-x"
        assert kwargs["secret"] == "secret-live-x"
        assert kwargs["endpoint"] == "users"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.stytch.source.stytch_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_stytch_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "sessions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_stytch_source.call_args.kwargs["db_incremental_field_last_value"] is None
