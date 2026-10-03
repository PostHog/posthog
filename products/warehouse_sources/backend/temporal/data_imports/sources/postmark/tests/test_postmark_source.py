from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postmark import (
    PostmarkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source import PostmarkSource


class TestPostmarkSource:
    def setup_method(self):
        self.source = PostmarkSource()
        self.team_id = 123
        self.config = PostmarkSourceConfig(server_token="test-server-token")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["bounces"])

        assert len(schemas) == 1
        assert schemas[0].name == "bounces"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source.validate_postmark_credentials"
    )
    def test_validate_credentials_success(self, mock_validate):
        mock_validate.return_value = (True, 200)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with(self.config.server_token)

    @parameterized.expand(
        [
            ("invalid_token_401", 401, "Invalid Postmark server API token"),
            ("missing_permissions_403", 403, "doesn't have the required permissions"),
            ("unreachable_none", None, "Couldn't reach Postmark"),
            ("server_error_500", 500, "Couldn't reach Postmark"),
            ("rate_limited_429", 429, "Couldn't reach Postmark"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source.validate_postmark_credentials"
    )
    def test_validate_credentials_failure_maps_status(self, _name, status, expected_substring, mock_validate):
        mock_validate.return_value = (False, status)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert expected_substring in error_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source.postmark_source")
    def test_source_for_pipeline(self, mock_postmark_source):
        mock_postmark_source.return_value = mock.MagicMock()

        inputs = mock.MagicMock()
        inputs.schema_name = "messages_outbound"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        call_kwargs = mock_postmark_source.call_args.kwargs
        assert call_kwargs["server_token"] == self.config.server_token
        assert call_kwargs["endpoint"] == "messages_outbound"
        assert call_kwargs["team_id"] == inputs.team_id
        assert call_kwargs["job_id"] == inputs.job_id
        assert call_kwargs["resumable_source_manager"] is manager
        # The webhook manager rides alongside the pull iterator so one sync covers both.
        assert isinstance(call_kwargs["webhook_source_manager"], WebhookSourceManager)

    def test_get_schemas_marks_only_bounces_webhook_capable(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        webhook_capable = {schema.name for schema in schemas if schema.supports_webhooks}
        # Only bounces has a Postmark trigger whose payload matches a table we already sync.
        assert webhook_capable == {"bounces"}
        assert not any(schema.webhook_only for schema in schemas)

    def test_webhook_resource_map_routes_bounces(self):
        assert self.source.webhook_resource_map == {"bounces": "Bounce"}
        # The template looks the schema id up under this key, so a rename breaks routing.
        assert self.source.webhook_mapping_key("bounces") == "Bounce"

    def test_webhook_template_requires_a_secret(self):
        template = self.source.webhook_template

        assert template is not None
        assert template.type == "warehouse_source_webhook"
        inputs_by_key = {item["key"]: item for item in template.inputs_schema}
        assert set(inputs_by_key) == {"signing_secret", "schema_mapping", "source_id"}
        # No bypass input exists, so an unauthenticated delivery can never be accepted.
        assert inputs_by_key["signing_secret"]["required"] is True
        assert inputs_by_key["signing_secret"]["secret"] is True

    def test_get_webhook_source_manager(self):
        inputs = mock.MagicMock()
        assert isinstance(self.source.get_webhook_source_manager(inputs), WebhookSourceManager)

    @parameterized.expand(
        [
            ("create_webhook", "create_postmark_webhook"),
            ("get_external_webhook_info", "get_postmark_webhook_info"),
            ("delete_webhook", "delete_postmark_webhook"),
        ]
    )
    def test_webhook_management_delegates_with_the_server_token(self, method_name, patched_name):
        with mock.patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.postmark.source.{patched_name}"
        ) as mock_fn:
            result = getattr(self.source, method_name)(self.config, "https://ph.example/webhook", self.team_id)

        mock_fn.assert_called_once_with(self.config.server_token, "https://ph.example/webhook")
        assert result is mock_fn.return_value
