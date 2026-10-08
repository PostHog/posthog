from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.genesyscloud import (
    GenesysCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.genesys_cloud import (
    GenesysCloudResumeConfig,
    genesys_cloud_source,
    validate_credentials as validate_genesys_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.settings import (
    DEFAULT_REGION,
    ENDPOINTS,
    GENESYS_CLOUD_ENDPOINTS,
    INCREMENTAL_FIELDS,
    REGIONS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GenesysCloudSource(ResumableSource[GenesysCloudSourceConfig, GenesysCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.genesys.cloud/platform/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GENESYSCLOUD

    @property
    def connection_host_fields(self) -> list[str]:
        # The client secret is sent to login.{region} and the token to api.{region}.
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            OAUTH2_PERMANENT_ERROR_MARKER: "Genesys Cloud rejected the client ID and secret. Check that the OAuth client uses the client credentials grant and belongs to the selected region, then reconnect.",
            "401 Client Error: Unauthorized for url": "Genesys Cloud rejected the access token. Check the client ID, client secret, and region, then reconnect.",
            "403 Client Error: Forbidden for url": "The Genesys Cloud OAuth client's role is missing a permission this table needs. Add the permission to the role, or deselect the table.",
            "Unknown Genesys Cloud region": "Select the Genesys Cloud region your organization is hosted in, then reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GENESYSCLOUD,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            keywords=["genesys", "purecloud", "contact center"],
            label="Genesys Cloud",
            caption="""Connect your Genesys Cloud organization to import calls, conversations, participants, users, and queues.

In Genesys Cloud, go to **Admin > Integrations > OAuth** and add a client with the **Client Credentials** grant type. Assign it a role with these permissions:

- `analytics:conversationDetail:view` for calls, conversations, and participants
- `routing:queue:view` for queues

Then select the region your organization is hosted in.""",
            iconPath="/static/services/genesys_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/genesys-cloud",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label=f"{label} ({domain})", value=domain)
                            for domain, label in REGIONS.items()
                        ],
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.genesys_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GenesysCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GenesysCloudSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in GENESYS_CLOUD_ENDPOINTS:
            return False, f"Genesys Cloud has no table named {schema_name}."
        return validate_genesys_cloud_credentials(config.region, config.client_id, config.client_secret, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GenesysCloudResumeConfig]:
        return ResumableSourceManager[GenesysCloudResumeConfig](inputs, GenesysCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: GenesysCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return genesys_cloud_source(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
