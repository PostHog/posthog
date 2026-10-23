from typing import cast

from requests import HTTPError

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.gcp_cloud_billing import (
    GcpCloudBillingCredentialsError,
    GcpCloudBillingResumeConfig,
    gcp_cloud_billing_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudbilling import (
    GcpCloudBillingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpCloudBillingSource(ResumableSource[GcpCloudBillingSourceConfig, GcpCloudBillingResumeConfig]):
    codebase_detection = detect(
        env=("^(GCP_CLOUD_BILLING|GCPCLOUDBILLING)_",),
        npm=("@google-cloud/billing", "@google-cloud/billing-budgets"),
        pypi=("google-cloud-billing", "google-cloud-billing-budgets"),
        composer=("google/cloud-billing", "google/cloud-billing-budgets"),
        go=("cloud.google.com/go/billing",),
        maven=(
            "com.google.cloud:google-cloud-billing",
            "com.google.cloud:google-cloud-billingbudgets",
            "com.google.cloud:google-cloud-billing-spring-starter",
            "com.google.cloud:google-cloud-billingbudgets-spring-starter",
        ),
        rubygems=("google-cloud-billing",),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://cloud.google.com/billing/docs/reference/rest"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDBILLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDBILLING,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Google Cloud Platform (Cloud Billing)",
            iconPath="/static/services/gcp_cloud_billing.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gcp-cloud-billing",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["gcp", "google cloud"],
            caption=(
                "Import billing accounts, project links, budgets, and the public price catalog. "
                "Detailed spend requires a separate BigQuery billing export. "
                "Enable the Cloud Billing API and Cloud Billing Budget API. "
                "Grant billing.accounts.list, billing.resourceAssociations.list, and billing.budgets.list on the accounts to sync."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Service account JSON key file",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["client_email", "private_key", "private_key_id", "token_uri"],
                        ),
                        required=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Google rejected the credentials. Replace the service account key and reconnect.",
            "403 Client Error": "Google denied access. Enable the billing APIs and grant the required billing permissions.",
            "Invalid GCP service account key": "Upload a valid service account JSON key file.",
            "Google rejected the service account key": "Replace the service account key and reconnect.",
            "Google token exchange refused a redirect": "Replace the service account key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: GcpCloudBillingSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            probe_credentials(config.key_file, schema_name)
        except GcpCloudBillingCredentialsError as error:
            return False, str(error)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 403 and schema_name is None:
                return True, None
            if status in (401, 403):
                return False, self.get_non_retryable_errors()[f"{status} Client Error"]
            raise
        return True, None

    def get_schemas(
        self,
        config: GcpCloudBillingSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: entry["description"] for name, entry in CANONICAL_DESCRIPTIONS.items()},
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GcpCloudBillingResumeConfig]:
        return ResumableSourceManager(inputs, GcpCloudBillingResumeConfig)

    def source_for_pipeline(
        self,
        config: GcpCloudBillingSourceConfig,
        resumable_source_manager: ResumableSourceManager[GcpCloudBillingResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gcp_cloud_billing_source(
            key_file=config.key_file,
            endpoint_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
