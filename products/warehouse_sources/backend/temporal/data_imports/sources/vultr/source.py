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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VultrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.vultr import (
    validate_credentials as validate_vultr_credentials,
    vultr_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VultrSource(SimpleSource[VultrSourceConfig]):
    # get_schemas is a static endpoint catalog with no I/O, so the table list is safe for public docs.
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://www.vultr.com/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VULTR

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Vultr API key is invalid or has been revoked. Generate a new key in the Vultr customer portal and reconnect.",
            "403 Client Error: Forbidden for url": "Your Vultr API key is being blocked. Check the API key's IP access control list in the Vultr customer portal and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: VultrSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every Vultr list endpoint is full-refresh: the API exposes no server-side timestamp filter.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: VultrSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_vultr_credentials(config.api_key, schema_name)

    def source_for_pipeline(self, config: VultrSourceConfig, inputs: SourceInputs) -> SourceResponse:
        resource = vultr_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=ENDPOINTS[inputs.schema_name].primary_keys,
            column_hints=resource.column_hints,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VULTR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Vultr",
            caption=(
                "Import your Vultr cloud infrastructure and billing data. Generate a personal access token "
                "under **Account > API** in the [Vultr customer portal](https://my.vultr.com/settings/#settingsapi). "
                "The token grants full account access; if API access is restricted, add PostHog's egress IPs to the "
                "API key's access control list."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/vultr",
            iconPath="/static/services/vultr.svg",
            keywords=["cloud", "infrastructure", "billing", "compute"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
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
