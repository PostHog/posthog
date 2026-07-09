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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WritesonicSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SUPPORTS_INCREMENTAL,
    WRITESONIC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.writesonic import (
    WritesonicResumeConfig,
    validate_credentials as validate_writesonic_credentials,
    writesonic_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WritesonicSource(ResumableSource[WritesonicSourceConfig, WritesonicResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WRITESONIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WRITESONIC,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Writesonic",
            caption="""Connect Writesonic to pull your GEO (generative engine optimization) data — brand visibility, rank, and mentions across AI platforms like ChatGPT and Perplexity — into the PostHog Data warehouse.

You'll need:

- A Writesonic **API key** with GEO API access (revealed in your account's API dashboard; requires a plan with API access)
- The **site URL** of the tracked website, exactly as configured in Writesonic (e.g. `https://example.com`)
- Optionally, a **project ID** to disambiguate when the same site is tracked in multiple projects
""",
            iconPath="/static/services/writesonic.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/writesonic",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["seo", "geo", "ai visibility", "content marketing"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Writesonic API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="site_url",
                        label="Site URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="bb2baeaa-a48c-482b-af00-67df964b5d2b",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WritesonicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in SUPPORTS_INCREMENTAL,
                supports_append=endpoint in SUPPORTS_INCREMENTAL,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=WRITESONIC_ENDPOINTS[endpoint].primary_keys,
                description="Only syncs the last 365 days on initial sync"
                if endpoint in SUPPORTS_INCREMENTAL
                else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: WritesonicSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_writesonic_credentials(
            api_key=config.api_key,
            site_url=config.site_url,
            project_id=config.project_id,
            schema_name=schema_name,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.writesonic.com": (
                "Writesonic rejected the API key. Generate a new key in your Writesonic API dashboard and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.writesonic.com": (
                "Your Writesonic plan does not include API access to GEO data. Upgrade to a plan with "
                "API access and reconnect."
            ),
            "404 Client Error: Not Found for url: https://api.writesonic.com": (
                "Writesonic could not find a tracked site for the configured URL. Check the site URL "
                "(and project ID, if set) against your Writesonic workspace."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WritesonicResumeConfig]:
        return ResumableSourceManager[WritesonicResumeConfig](inputs, WritesonicResumeConfig)

    def source_for_pipeline(
        self,
        config: WritesonicSourceConfig,
        resumable_source_manager: ResumableSourceManager[WritesonicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return writesonic_source(
            api_key=config.api_key,
            site_url=config.site_url,
            project_id=config.project_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
