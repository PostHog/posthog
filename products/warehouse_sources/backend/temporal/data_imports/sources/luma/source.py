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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LumaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.luma import (
    LumaResumeConfig,
    luma_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.luma.settings import ENDPOINTS, LUMA_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LumaSource(ResumableSource[LumaSourceConfig, LumaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LUMA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LUMA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Luma",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Luma API key to pull your events, guests, and people into the PostHog Data warehouse.

You can create an API key under **Settings → Developer** in [Luma](https://luma.com) — API access requires a Luma Plus subscription. Calendar API keys are scoped to a single calendar; use an organization API key to import across calendars.
""",
            iconPath="/static/services/luma.png",
            docsUrl="https://posthog.com/docs/cdp/sources/luma",
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.luma.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://public-api.luma.com": "Your Luma API key is invalid or has been revoked. Generate a new key under Settings → Developer in Luma, then reconnect.",
            "403 Client Error: Forbidden for url: https://public-api.luma.com": "Your Luma API key does not have access to this data. Check the key's calendar or organization scope, then reconnect.",
        }

    def get_schemas(
        self,
        config: LumaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Luma's cursor pagination has no server-side
        # updated-since filter (list-events only bounds on event start time), so there is no
        # reliable timestamp cursor to advance an incremental sync.
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
        self, config: LumaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key grants read access to every endpoint on its calendar/organization, so a
        # single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LumaResumeConfig]:
        return ResumableSourceManager[LumaResumeConfig](inputs, LumaResumeConfig)

    def source_for_pipeline(
        self,
        config: LumaSourceConfig,
        resumable_source_manager: ResumableSourceManager[LumaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in LUMA_ENDPOINTS:
            raise ValueError(f"Unknown Luma schema '{inputs.schema_name}'")

        return luma_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
