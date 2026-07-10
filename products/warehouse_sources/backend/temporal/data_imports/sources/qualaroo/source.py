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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import QualarooSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.qualaroo import (
    QualarooResumeConfig,
    qualaroo_source,
    validate_credentials as _validate_qualaroo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.settings import (
    ENDPOINTS,
    QUALAROO_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QualarooSource(ResumableSource[QualarooSourceConfig, QualarooResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUALAROO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.QUALAROO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Qualaroo",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Qualaroo API key and secret to pull your survey (nudge) data into the PostHog Data warehouse.

You can find your API key and secret under **Settings → API** in [Qualaroo](https://app.qualaroo.com/). They authenticate the REST Reporting API with read access to your nudges.
""",
            iconPath="/static/services/qualaroo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/qualaroo",
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
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.qualaroo.com": "Your Qualaroo API key or secret is invalid or has been revoked. Generate a new pair under Settings → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.qualaroo.com": "Your Qualaroo credentials do not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: QualarooSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — the nudges list exposes no reliably ordered
        # server-side timestamp filter, so there is no incremental cursor to advance.
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
        self, config: QualarooSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The key/secret pair is account-wide, so a single probe validates access to every schema.
        return _validate_qualaroo_credentials(config.api_key, config.api_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[QualarooResumeConfig]:
        return ResumableSourceManager[QualarooResumeConfig](inputs, QualarooResumeConfig)

    def source_for_pipeline(
        self,
        config: QualarooSourceConfig,
        resumable_source_manager: ResumableSourceManager[QualarooResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in QUALAROO_ENDPOINTS:
            raise ValueError(f"Unknown Qualaroo schema '{inputs.schema_name}'")

        return qualaroo_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
