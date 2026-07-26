from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.gcp_cloud_billing import (
    ServiceAccountKey,
    gcp_cloud_billing_source,
    validate_credentials as validate_gcp_cloud_billing_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudbilling import (
    GcpCloudBillingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _service_account_key(config: GcpCloudBillingSourceConfig) -> ServiceAccountKey:
    return ServiceAccountKey(
        project_id=config.key_file.project_id,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )


@SourceRegistry.register
class GcpCloudBillingSource(SimpleSource[GcpCloudBillingSourceConfig]):
    api_docs_url = "https://cloud.google.com/billing/docs/reference/rest"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDBILLING

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Returned by Google's token endpoint when the signed assertion is rejected: a rotated
            # or revoked private key, or a deleted service account. A new key file is the only fix.
            "invalid_grant": "Google rejected the service account key. Please upload a current JSON key file for a service account that still exists.",
            # Raised while parsing the uploaded key's PEM body when it is truncated or corrupted,
            # which no amount of retrying repairs.
            "Unable to load PEM file": "The service account key file looks corrupted. Please download a fresh JSON key from Google Cloud and upload it again.",
            # 403 carrying this body means the API is switched off for the service account's
            # project, so every call fails until someone enables it.
            "has not been used in project": "Enable the Cloud Billing API and the Cloud Billing Budgets API for your Google Cloud project, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://cloudbilling.googleapis.com": "Google denied access to your billing data. Please grant the service account the Billing Account Viewer role on the billing accounts you want to sync.",
            "403 Client Error: Forbidden for url: https://billingbudgets.googleapis.com": "Google denied access to your budgets. Please grant the service account the Billing Account Viewer role and enable the Cloud Billing Budgets API.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GcpCloudBillingSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: GcpCloudBillingSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_gcp_cloud_billing_credentials(_service_account_key(config), config.billing_account_id)

    def source_for_pipeline(self, config: GcpCloudBillingSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return gcp_cloud_billing_source(
            key=_service_account_key(config),
            billing_account_id=config.billing_account_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_CLOUD_BILLING,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Google Cloud Billing",
            keywords=["gcp", "google cloud", "finops", "cost"],
            caption="""Sync your Google Cloud billing accounts, project links, service and SKU price catalog, and budgets into the PostHog Data warehouse.

Create a service account in Google Cloud, give it the **Billing Account Viewer** role on the billing accounts you want to sync, enable the **Cloud Billing API** and the **Cloud Billing Budgets API**, then upload its JSON key file.

This API covers billing metadata, not spend. For cost and usage line items, set up [BigQuery billing export](https://cloud.google.com/billing/docs/how-to/export-data-bigquery) and connect the BigQuery source.""",
            iconPath="/static/services/gcp_cloud_billing.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gcp-cloud-billing",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Google Cloud JSON key file",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["project_id", "private_key", "private_key_id", "client_email", "token_uri"],
                        ),
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="billing_account_id",
                        label="Billing account ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="012345-567890-ABCDEF",
                        secret=False,
                    ),
                ],
            ),
        )
