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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GorgiasSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.gorgias import (
    GorgiasResumeConfig,
    gorgias_source,
    validate_credentials as validate_gorgias_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.settings import (
    ENDPOINTS,
    GORGIAS_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GorgiasSource(ResumableSource[GorgiasSourceConfig, GorgiasResumeConfig]):
    api_docs_url = "https://developers.gorgias.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GORGIAS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Gorgias authentication failed. Check your email and API key.",
            "403 Client Error: Forbidden for url": "Your Gorgias API key does not have access to this resource. Check the integration's permissions.",
        }

    def get_schemas(
        self,
        config: GorgiasSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Gorgias has no server-side timestamp filter. Incremental-capable endpoints sort
        # their cursor field newest-first and stop paginating at the watermark; the rest
        # stay full-refresh. Cursor pagination lets any sync resume mid-stream via the
        # ResumableSourceManager.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=GORGIAS_ENDPOINTS[endpoint].supports_incremental,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GorgiasSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_gorgias_credentials(config.gorgias_domain, config.email, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GorgiasResumeConfig]:
        return ResumableSourceManager[GorgiasResumeConfig](inputs, GorgiasResumeConfig)

    def source_for_pipeline(
        self,
        config: GorgiasSourceConfig,
        resumable_source_manager: ResumableSourceManager[GorgiasResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gorgias_source(
            domain=config.gorgias_domain,
            email=config.email,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GORGIAS,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Gorgias",
            caption="""Enter your Gorgias credentials to pull your helpdesk data into the PostHog Data warehouse.

Create an API key in your Gorgias account under **Settings → REST API**. Use the email of the account that owns the key together with the key itself.

This source authenticates with HTTP Basic Auth (email + API key) and requires read access to the endpoints you want to sync (tickets, messages, customers, users, satisfaction surveys, tags, views, teams, macros).""",
            iconPath="/static/services/gorgias.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gorgias",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="gorgias_domain",
                        label="Gorgias domain (subdomain)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-company",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="email",
                        label="Account email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@your-company.com",
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
