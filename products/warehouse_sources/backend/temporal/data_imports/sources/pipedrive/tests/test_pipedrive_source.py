import datetime

import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pipedrive import (
    PipedriveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source import PipedriveSource


class TestPipedriveSource:
    def setup_method(self) -> None:
        self.source = PipedriveSource()
        self.team_id = 123
        self.config = PipedriveSourceConfig(company_domain="acme", api_token="token")

    def test_v1_is_deprecated_with_vendor_sunset_and_default_is_v2(self) -> None:
        # New sources start on v2; v1 stays supported but carries the vendor's sunset date so the
        # generic in-product deprecation warning fires.
        assert self.source.default_version == "v2"
        assert set(self.source.supported_versions) == {"v1", "v2"}

        deprecation = self.source.get_version_deprecation("v1")
        assert deprecation is not None
        assert deprecation.sunset_at == datetime.date(2025, 12, 31)
        assert self.source.get_version_deprecation("v2") is None

    def test_company_domain_is_connection_host_field(self) -> None:
        assert self.source.connection_host_fields == ["company_domain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.pipedrive.com/api/v2/deals?limit=500",
            "403 Client Error: Forbidden for url: https://acme.pipedrive.com/api/v1/activities?limit=500&start=0",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.pipedrive.com/api/v2/deals",
            "500 Server Error for url: https://acme.pipedrive.com/api/v1/notes",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["deals"])
        assert len(schemas) == 1
        assert schemas[0].name == "deals"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_message",
        [
            (200, None, True, None),
            (200, "deals", True, None),
            (403, None, True, None),
            (403, "deals", False, "Invalid Pipedrive API token or insufficient permissions"),
            (401, None, False, "Invalid Pipedrive API token or insufficient permissions"),
            (500, None, False, "Could not validate Pipedrive credentials"),
            (None, None, False, "Could not validate Pipedrive credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.validate_pipedrive_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        status: int | None,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = status

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("acme", "token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.validate_pipedrive_credentials"
    )
    def test_validate_credentials_rejects_invalid_domain(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = ValueError("Invalid Pipedrive company domain: 'evil.com'")
        is_valid, message = self.source.validate_credentials(
            PipedriveSourceConfig(company_domain="evil.com", api_token="token"), self.team_id
        )
        assert is_valid is False
        assert message is not None and "Invalid Pipedrive company domain" in message

    @pytest.mark.parametrize(
        "pinned_version, expected_version",
        [
            ("v2", "v2"),
            ("v1", "v1"),
            # A missing pin resolves to the source's default (v2).
            (None, "v2"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.pipedrive_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_pipedrive_source: mock.MagicMock, pinned_version: str | None, expected_version: str
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "deals"
        inputs.api_version = pinned_version
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_pipedrive_source.assert_called_once()
        kwargs = mock_pipedrive_source.call_args.kwargs
        assert kwargs["company_domain"] == "acme"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "deals"
        assert kwargs["api_version"] == expected_version
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.pipedrive_source")
    def test_source_for_pipeline_normalizes_company_domain(self, mock_pipedrive_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "deals"

        self.source.source_for_pipeline(
            PipedriveSourceConfig(company_domain="https://Acme.pipedrive.com", api_token="token"),
            mock.MagicMock(),
            inputs,
        )

        assert mock_pipedrive_source.call_args.kwargs["company_domain"] == "acme"

    @pytest.mark.parametrize(
        "api_version, expected",
        [
            # Only the schemas backfilled from the API v2 collections can take a v2 delivery.
            ("v2", {"activities", "deals", "organizations", "persons", "pipelines", "products", "stages"}),
            # A v1 pin still polls `activities` from the v1 collection, whose rows are shaped
            # differently to the v2 payload we would push into the same table.
            ("v1", {"deals", "organizations", "persons", "pipelines", "products", "stages"}),
        ],
    )
    def test_only_v2_shaped_schemas_support_webhooks(self, api_version: str, expected: set[str]) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)

        assert {schema.name for schema in schemas if schema.supports_webhooks} == expected

    def test_webhook_mapping_keys_are_the_pipedrive_entity_names(self) -> None:
        # Deliveries are routed by `meta.entity`, so a schema whose key isn't the singular entity
        # name would have every one of its events dropped as unmapped.
        webhook_schemas = [s.name for s in self.source.get_schemas(self.config, self.team_id) if s.supports_webhooks]

        assert {name: self.source.webhook_mapping_key(name) for name in webhook_schemas} == {
            "activities": "activity",
            "deals": "deal",
            "organizations": "organization",
            "persons": "person",
            "pipelines": "pipeline",
            "products": "product",
            "stages": "stage",
        }

    def test_webhook_template_verifies_basic_auth_credentials(self) -> None:
        template = self.source.webhook_template

        assert template is not None
        assert template.type == "warehouse_source_webhook"
        input_keys = {item["key"] for item in template.inputs_schema}
        assert {"http_auth_user", "http_auth_password"} <= input_keys

    def test_webhook_fields_match_the_template_inputs(self) -> None:
        # The values a user pastes after a manual setup land on the hog function under these
        # keys, so a mismatch leaves the template with no credentials to check against.
        webhook_fields = self.source.get_source_config.webhookFields or []
        assert [f.name for f in webhook_fields if isinstance(f, SourceFieldInputConfig)] == [
            "http_auth_user",
            "http_auth_password",
        ]

    @pytest.mark.parametrize(
        "method_name, patched",
        [
            ("create_webhook", "create_pipedrive_webhook"),
            ("delete_webhook", "delete_pipedrive_webhook"),
            ("get_external_webhook_info", "get_pipedrive_webhook_info"),
        ],
    )
    def test_webhook_management_passes_domain_then_token(self, method_name: str, patched: str) -> None:
        with mock.patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.{patched}"
        ) as mocked:
            getattr(self.source, method_name)(self.config, "https://webhooks.example/hook", self.team_id)

        mocked.assert_called_once_with("acme", "token", "https://webhooks.example/hook")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.source.pipedrive_source")
    def test_source_for_pipeline_passes_a_webhook_manager(self, mock_pipedrive_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "deals"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert isinstance(mock_pipedrive_source.call_args.kwargs["webhook_source_manager"], WebhookSourceManager)
