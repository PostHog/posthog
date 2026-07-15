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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HyperspellSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HyperspellResumeConfig,
    hyperspell_source,
    validate_credentials as validate_hyperspell_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HyperspellSource(ResumableSource[HyperspellSourceConfig, HyperspellResumeConfig]):
    # get_schemas iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in the public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HYPERSPELL

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the API key is sent to (api.hyperspell.com vs api.eu.hyperspell.com)
        # and `user_id` sets the `X-As-User` identity the key acts as. Changing either retargets the
        # stored key, so both must re-require the secret to be re-entered.
        return ["region", "user_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HYPERSPELL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hyperspell",
            caption=(
                "Sync your Hyperspell memories, connections, integrations, extracted entities, query logs "
                "and context documents. Create an API key in the **[Hyperspell dashboard](https://dashboard.hyperspell.com)** "
                "and paste it below, choosing the region the key was created in.\n\n"
                "Hyperspell data is scoped per user: set a user ID to sync that user's memories, or leave "
                "it blank to sync app-scoped data only."
            ),
            iconPath="/static/services/hyperspell.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/hyperspell",
            keywords=["ai", "memory", "agents", "context"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Hyperspell API key",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.hyperspell.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.hyperspell.com)", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="user_id",
                        label="User ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Sync data for a specific user",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Hyperspell API key. Please check your API key and its region, and reconnect.",
            "403 Client Error": "Your Hyperspell API key lacks the required permissions. Please check the key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HyperspellSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Hyperspell has no server-side updated-since/created-since filter on any list
                # endpoint, so every schema is full-refresh only.
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HyperspellSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_hyperspell_credentials(config.api_key, config.region, config.user_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HyperspellResumeConfig]:
        return ResumableSourceManager[HyperspellResumeConfig](inputs, HyperspellResumeConfig)

    def source_for_pipeline(
        self,
        config: HyperspellSourceConfig,
        resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hyperspell_source(
            api_key=config.api_key,
            region=config.region,
            user_id=config.user_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
