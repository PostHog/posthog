from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moxie import MoxieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.moxie import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    moxie_source,
    validate_credentials as validate_moxie_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MoxieSource(SimpleSource[MoxieSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://help.withmoxie.com/en/collections/5482062-public-api-endpoints"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOXIE

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API key is sent; retargeting it must re-require the key.
        return ["base_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Moxie rejected the API key. Check the key and workspace base URL in Workspace settings > Connected Apps > Integrations, then reconnect.",
            "403 Client Error": "The Moxie API key does not have permission for this workspace.",
            HOST_NOT_ALLOWED_ERROR: "The Moxie workspace base URL is not allowed. Please use a publicly reachable host.",
            HTTP_NOT_ALLOWED_ERROR: "The Moxie workspace base URL must use HTTPS. Please update it to use https://.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MoxieSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Moxie's Public API exposes no pagination, cursors, or server-side timestamp filters, so
        # every table is full refresh only.
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: MoxieSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_moxie_credentials(config.base_url, config.api_key, team_id)

    def source_for_pipeline(self, config: MoxieSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return moxie_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MOXIE,
            category=DataWarehouseSourceCategory.CRM,
            label="Moxie",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["freelance crm", "invoicing", "time tracking"],
            caption="""Enter your Moxie workspace base URL and API key to pull your clients, projects, invoices, and more into the PostHog Data warehouse.

Go to **Workspace settings > Connected Apps > Integrations** in Moxie and click **Enable Custom Integration** to see your workspace's base URL and API key.""",
            iconPath="/static/services/moxie.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Workspace base URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://pod00.withmoxie.dev/api/public",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
