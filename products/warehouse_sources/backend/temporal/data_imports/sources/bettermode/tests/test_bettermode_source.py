import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.bettermode import (
    BettermodeResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source import BettermodeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BettermodeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBettermodeSource:
    def setup_method(self):
        self.source = BettermodeSource()
        self.team_id = 123
        self.config = BettermodeSourceConfig(region="us", client_id="client", client_secret="secret", network_id="net")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BETTERMODE

    def test_get_source_config_ships_released(self):
        config = self.source.get_source_config

        assert config.name.value == "Bettermode"
        assert config.label == "Bettermode"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/bettermode.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["region", "client_id", "client_secret", "network_id"]

    def test_region_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu"}

    def test_connection_host_fields_gate_credential_retargeting(self):
        # Removing either field lets an editor retarget the preserved client secret at a
        # different host/community without re-entering it.
        assert self.source.connection_host_fields == ["region", "network_id"]

    def test_client_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Bettermode API error (status 401): Unauthorized",
            "Bettermode API error (status 403): Forbidden resource",
            "Bettermode API error (status 404): App not found",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "Bettermode API error (retryable): status=429",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only `posts` has a server-side timestamp filter; everything else is full refresh.
        assert incremental == {"posts"}

    def test_posts_schema_advertises_timestamp_cursors(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["posts"].incremental_fields == INCREMENTAL_FIELDS["posts"]
        assert [f["field"] for f in schemas["posts"].incremental_fields] == ["createdAt", "publishedAt", "updatedAt"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["posts"])
        assert len(schemas) == 1
        assert schemas[0].name == "posts"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "Bettermode API error (status 404): App not found"),
                False,
                "Bettermode API error (status 404): App not found",
            ),
            ((False, None), False, "Invalid Bettermode credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source.validate_bettermode_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("us", "client", "secret", "net")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BettermodeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source.bettermode_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bm_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        inputs.incremental_field = "createdAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bm_source.assert_called_once()
        kwargs = mock_bm_source.call_args.kwargs
        assert kwargs["region"] == "us"
        assert kwargs["client_id"] == "client"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["network_id"] == "net"
        assert kwargs["endpoint"] == "posts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"
        assert kwargs["incremental_field"] == "createdAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.source.bettermode_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_bm_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_bm_source.call_args.kwargs["db_incremental_field_last_value"] is None
