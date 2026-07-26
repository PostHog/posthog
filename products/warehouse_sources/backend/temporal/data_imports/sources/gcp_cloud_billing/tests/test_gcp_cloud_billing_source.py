from typing import Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldFileUploadConfig, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.source import (
    GcpCloudBillingSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudbilling import (
    GcpCloudBillingKeyFileConfig,
    GcpCloudBillingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.source"


def _config(billing_account_id: Optional[str] = None) -> GcpCloudBillingSourceConfig:
    return GcpCloudBillingSourceConfig(
        key_file=GcpCloudBillingKeyFileConfig(
            project_id="posthog-billing",
            private_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
            private_key_id="key-id",
            client_email="sa@posthog-billing.iam.gserviceaccount.com",
            token_uri="https://oauth2.googleapis.com/token",
        ),
        billing_account_id=billing_account_id,
    )


class TestGcpCloudBillingSource:
    def setup_method(self) -> None:
        self.source = GcpCloudBillingSource()
        self.team_id = 123
        self.config = _config()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.GCPCLOUDBILLING

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "GcpCloudBilling"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/gcp_cloud_billing.png"
        assert [field.name for field in config.fields] == ["key_file", "billing_account_id"]

    def test_key_file_upload_requires_the_fields_needed_to_mint_a_token(self) -> None:
        key_file_field = next(
            field for field in self.source.get_source_config.fields if isinstance(field, SourceFieldFileUploadConfig)
        )

        assert key_file_field.required is True
        assert key_file_field.fileFormat.keys == [
            "project_id",
            "private_key",
            "private_key_id",
            "client_email",
            "token_uri",
        ]

    def test_billing_account_id_is_optional(self) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == "billing_account_id"
        )

        assert field.required is False
        assert field.secret is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "('invalid_grant: Invalid JWT Signature.', {'error': 'invalid_grant'})",
            "ValueError: Unable to load PEM file. ... InvalidData(InvalidPadding)",
            "403 Client Error: Forbidden for url: https://cloudbilling.googleapis.com/v1/billingAccounts - "
            "Cloud Billing API has not been used in project 12345 before or it is disabled.",
            "403 Client Error: Forbidden for url: https://cloudbilling.googleapis.com/v1/services",
            "403 Client Error: Forbidden for url: https://billingbudgets.googleapis.com/v1/billingAccounts/A/budgets",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error: Internal Server Error for url: https://cloudbilling.googleapis.com/v1/services",
            "429 Client Error: Too Many Requests for url: https://cloudbilling.googleapis.com/v1/services",
            # Mid-sync 401s are handled by re-minting the access token, not by disabling the source.
            "401 Client Error: Unauthorized for url: https://cloudbilling.googleapis.com/v1/services",
        ],
    )
    def test_non_retryable_errors_leave_transient_failures_alone(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["skus"])

        assert [schema.name for schema in schemas] == ["skus"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["cost_line_items"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        documented = self.source.get_documented_tables()

        assert {table["name"] for table in documented} == set(ENDPOINTS)
        assert all(table["description"] for table in documented)
        assert all(table["sync_methods"] == ["Full refresh"] for table in documented)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        canonical = self.source.get_canonical_descriptions()

        assert set(canonical) == set(ENDPOINTS)
        assert all(entry.get("columns", {}).get("name") for entry in canonical.values())

    @pytest.mark.parametrize(
        "returned, expected",
        [
            ((True, None), (True, None)),
            ((False, "Could not authenticate"), (False, "Could not authenticate")),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_gcp_cloud_billing_credentials")
    def test_validate_credentials_passes_through_the_transport_result(
        self,
        mock_validate: mock.MagicMock,
        returned: tuple[bool, Optional[str]],
        expected: tuple[bool, Optional[str]],
    ) -> None:
        mock_validate.return_value = returned

        assert self.source.validate_credentials(_config("A"), self.team_id) == expected

        key, billing_account_id = mock_validate.call_args.args
        assert key.client_email == "sa@posthog-billing.iam.gserviceaccount.com"
        assert billing_account_id == "A"

    @mock.patch(f"{_SOURCE_MODULE}.gcp_cloud_billing_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "skus"

        self.source.source_for_pipeline(_config("012345-567890-ABCDEF"), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "skus"
        assert kwargs["billing_account_id"] == "012345-567890-ABCDEF"
        assert kwargs["key"].private_key_id == "key-id"
        assert kwargs["key"].token_uri == "https://oauth2.googleapis.com/token"
