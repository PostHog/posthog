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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SvixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.settings import ENDPOINTS, SVIX_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.svix import (
    SvixResumeConfig,
    svix_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SvixSource(ResumableSource[SvixSourceConfig, SvixResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SVIX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SVIX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Svix",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Svix API key to pull your webhook platform data into the PostHog Data warehouse.

You can create an API key under **Settings → API Access** in the [Svix dashboard](https://dashboard.svix.com/). The region is encoded in the key (the `sk_` prefix), so use the key for the environment you want to sync. The key grants read access to your applications and event types.
""",
            iconPath="/static/services/svix.png",
            docsUrl="https://posthog.com/docs/cdp/sources/svix",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.svix.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.svix.com": "Your Svix API key is invalid or has been revoked. Generate a new key under Settings → API Access, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.svix.com": "Your Svix API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SvixSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Svix's list endpoints expose no server-side
        # updated-since filter, so there is no incremental cursor to advance.
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
        self, config: SvixSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SvixResumeConfig]:
        return ResumableSourceManager[SvixResumeConfig](inputs, SvixResumeConfig)

    def source_for_pipeline(
        self,
        config: SvixSourceConfig,
        resumable_source_manager: ResumableSourceManager[SvixResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SVIX_ENDPOINTS:
            raise ValueError(f"Unknown Svix schema '{inputs.schema_name}'")

        return svix_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
