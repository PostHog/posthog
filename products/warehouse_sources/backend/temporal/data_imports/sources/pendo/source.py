from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.pendo import (
    PendoResumeConfig,
    pendo_source,
    validate_credentials as validate_pendo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PendoSource(ResumableSource[PendoSourceConfig, PendoResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://engageapi.pendo.io"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PENDO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PENDO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Pendo",
            caption="""Enter your Pendo integration key to pull your Pendo data into the PostHog Data warehouse.

Create an integration key in Pendo under **Settings > Integrations > Integration Keys** (only Pendo admins can view these). The key is specific to your subscription's data region, so make sure the region below matches the domain you log in with.
""",
            iconPath="/static/services/pendo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pendo",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="integration_key",
                        label="Integration key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Pendo integration key",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Data region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (app.pendo.io)", value="us"),
                            SourceFieldSelectConfigOption(label="US1 (us1.app.pendo.io)", value="us1"),
                            SourceFieldSelectConfigOption(label="EU (app.eu.pendo.io)", value="eu"),
                            SourceFieldSelectConfigOption(label="Japan (app.jpn.pendo.io)", value="jp"),
                            SourceFieldSelectConfigOption(label="Australia (app.au.pendo.io)", value="au"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PendoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh: Pendo exposes no server-side timestamp filter for
        # this metadata, so neither incremental nor append would avoid re-reading every row.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
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
        self, config: PendoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_pendo_credentials(config.integration_key, config.region)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": (
                "Your Pendo integration key is invalid or has been revoked. Generate a new key in Pendo "
                "(Settings > Integrations > Integration Keys) and reconnect."
            ),
            "403 Client Error": (
                "Your Pendo integration key is missing the required permissions. Make sure it has read "
                "access (write access is needed for the aggregation endpoint) and reconnect."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PendoResumeConfig]:
        return ResumableSourceManager[PendoResumeConfig](inputs, PendoResumeConfig)

    def source_for_pipeline(
        self,
        config: PendoSourceConfig,
        resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pendo_source(
            integration_key=config.integration_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
