from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.salesforcemarketingcloud import (
    SalesforceMarketingCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.salesforce_marketing_cloud import (
    AUTH_FAILURE_MESSAGE,
    SalesforceMarketingCloudResumeConfig,
    salesforce_marketing_cloud_source,
    validate_credentials as validate_salesforce_marketing_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.settings import (
    SALESFORCE_MARKETING_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SalesforceMarketingCloudSource(
    ResumableSource[SalesforceMarketingCloudSourceConfig, SalesforceMarketingCloudResumeConfig]
):
    api_docs_url = "https://developer.salesforce.com/docs/marketing/marketing-cloud/references/mc_rest"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESFORCEMARKETINGCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SALESFORCE_MARKETING_CLOUD,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["sfmc", "exacttarget", "marketing cloud engagement"],
            label="Salesforce Marketing Cloud",
            caption=(
                "Connect Marketing Cloud Engagement with a **Server-to-Server** installed package, created under "
                "**Setup → Apps → Installed Packages** in Marketing Cloud.\n\n"
                "Enter the package's client ID and client secret plus your tenant subdomain — the string in your "
                "API endpoints, for example `mc563885gzs27c5t9-63k636ttgm` in "
                "`https://mc563885gzs27c5t9-63k636ttgm.auth.marketingcloudapis.com`. If your account has several "
                "business units, add the MID of the one you want to sync.\n\n"
                "The package needs read scopes for the data you sync: **Email Read**, **List and Subscribers Read**, "
                "**Tracking Events Read**, **Data Extensions Read**, **Saved Content Read**, **Journeys Read** and "
                "**Campaign Read**. Data extensions sync as metadata — the catalog and its field definitions, not "
                "row contents."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/salesforce-marketing-cloud",
            iconPath="/static/services/salesforce_marketing_cloud.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Tenant subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mc563885gzs27c5t9-63k636ttgm",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Business unit MID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to use the package's default business unit",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_FAILURE_MESSAGE: (
                "Marketing Cloud rejected the installed package credentials. Check the client ID, client secret "
                "and business unit MID, and that the package uses Server-to-Server integration."
            ),
            "401 Client Error: Unauthorized": (
                "Marketing Cloud rejected the access token. Reconnect the source with fresh installed package "
                "credentials."
            ),
            "403 Client Error: Forbidden": (
                "The installed package is missing the scopes needed to sync this table. Add the matching read "
                "scope in Marketing Cloud (Setup → Apps → Installed Packages) and reconnect."
            ),
        }

    def get_schemas(
        self,
        config: SalesforceMarketingCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=bool(endpoint.incremental_fields),
                supports_append=bool(endpoint.incremental_fields),
                incremental_fields=endpoint.incremental_fields,
                should_sync_default=endpoint.should_sync_default,
                detected_primary_keys=endpoint.primary_keys,
            )
            for name, endpoint in SALESFORCE_MARKETING_CLOUD_ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: SalesforceMarketingCloudSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_salesforce_marketing_cloud_credentials(
            config.subdomain, config.client_id, config.client_secret, config.account_id
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[SalesforceMarketingCloudResumeConfig]:
        return ResumableSourceManager[SalesforceMarketingCloudResumeConfig](
            inputs, SalesforceMarketingCloudResumeConfig
        )

    def source_for_pipeline(
        self,
        config: SalesforceMarketingCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SALESFORCE_MARKETING_CLOUD_ENDPOINTS:
            raise ValueError(f"Unknown Salesforce Marketing Cloud endpoint: {inputs.schema_name}")

        return salesforce_marketing_cloud_source(
            subdomain=config.subdomain,
            client_id=config.client_id,
            client_secret=config.client_secret,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            # SOAP and REST cursors are different shapes, so each endpoint keeps its resume state
            # in its own Redis slot.
            resumable_source_manager=resumable_source_manager.with_namespace(inputs.schema_name),
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
