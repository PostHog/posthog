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
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.drata import (
    DrataResumeConfig,
    drata_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drata.settings import (
    DRATA_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DrataSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DrataSource(ResumableSource[DrataSourceConfig, DrataResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DRATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DRATA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Drata",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Drata API key to pull your compliance data into the PostHog Data warehouse.

You can create an API key under **Settings → API keys** in [Drata](https://app.drata.com/). A key with **read** scopes is sufficient; pick the region that matches your Drata account.
""",
            iconPath="/static/services/drata.png",
            docsUrl="https://posthog.com/docs/cdp/sources/drata",
            keywords=["compliance", "grc", "soc2", "audit"],
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Drata region",
                        required=True,
                        defaultValue="US",
                        options=[
                            SourceFieldSelectConfigOption(label="North America", value="US"),
                            SourceFieldSelectConfigOption(label="Europe", value="EU"),
                            SourceFieldSelectConfigOption(label="Asia-Pacific", value="APAC"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.drata.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The host varies by region (public-api.drata.com / public-api.eu.drata.com /
        # public-api.apac.drata.com), so match on the shared prefix.
        return {
            "401 Client Error: Unauthorized for url: https://public-api": "Your Drata API key is invalid or has expired. Create a new API key under Settings → API keys in Drata, then reconnect.",
            "403 Client Error: Forbidden for url: https://public-api": "Your Drata API key does not have permission to read this data. Grant the key the matching read scope in Drata, then reconnect.",
            "412 Client Error: Precondition Failed for url: https://public-api": "You must accept the Drata API terms and conditions in your Drata account before syncing.",
        }

    def get_schemas(
        self,
        config: DrataSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only events exposes a server-side timestamp filter (createdAtStartDate), so it is the
        # only endpoint that supports incremental sync.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=DRATA_ENDPOINTS[endpoint].should_sync_default,
                detected_primary_keys=DRATA_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DrataSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide; one probe validates the token itself. Per-endpoint scopes
        # are surfaced at sync time via get_non_retryable_errors.
        return validate_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DrataResumeConfig]:
        return ResumableSourceManager[DrataResumeConfig](inputs, DrataResumeConfig)

    def source_for_pipeline(
        self,
        config: DrataSourceConfig,
        resumable_source_manager: ResumableSourceManager[DrataResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in DRATA_ENDPOINTS:
            raise ValueError(f"Unknown Drata schema '{inputs.schema_name}'")

        return drata_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
