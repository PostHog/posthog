import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShortcutSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.source import ShortcutSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestShortcutSource:
    def setup_method(self):
        self.source = ShortcutSource()
        self.team_id = 123
        self.config = ShortcutSourceConfig(api_token="test-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SHORTCUT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Shortcut"
        assert config.label == "Shortcut"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/shortcut.png"
        assert len(config.fields) == 1

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_stories_supports_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["stories"].supports_incremental is True
        assert schemas["stories"].supports_append is True
        # Story incremental fields are updated_at (default) and created_at.
        assert {f["field"] for f in schemas["stories"].incremental_fields} == {"updated_at", "created_at"}

        for name, schema in schemas.items():
            if name == "stories":
                continue
            assert schema.supports_incremental is False, name
            assert schema.supports_append is False, name
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["members"])
        assert len(schemas) == 1
        assert schemas[0].name == "members"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])
        assert schemas == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.app.shortcut.com/api/v3/members",
            "403 Client Error: Forbidden for url: https://api.app.shortcut.com/api/v3/stories/search",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests",
            "500 Server Error: Internal Server Error",
        ],
    )
    def test_non_retryable_errors_ignore_transient_failures(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Shortcut API token."), False, "Invalid Shortcut API token."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.source.validate_shortcut_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_source_for_pipeline_plumbs_arguments(self):
        inputs = mock.Mock()
        inputs.schema_name = "stories"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updated_at"
        inputs.logger = mock.Mock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.source.shortcut_source"
        ) as mock_shortcut_source:
            self.source.source_for_pipeline(self.config, inputs)

        mock_shortcut_source.assert_called_once_with(
            api_token="test-token",
            endpoint="stories",
            logger=inputs.logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="updated_at",
        )

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        inputs = mock.Mock()
        inputs.schema_name = "members"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        inputs.incremental_field = None
        inputs.logger = mock.Mock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.source.shortcut_source"
        ) as mock_shortcut_source:
            self.source.source_for_pipeline(self.config, inputs)

        _, kwargs = mock_shortcut_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
