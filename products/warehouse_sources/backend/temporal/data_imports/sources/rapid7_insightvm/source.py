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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    Rapid7InsightvmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.rapid7_insightvm import (
    Rapid7InsightvmResumeConfig,
    rapid7_insightvm_source,
    validate_credentials as validate_rapid7_insightvm_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.settings import (
    INCREMENTAL_FIELDS,
    RAPID7_INSIGHTVM_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Rapid7InsightvmSource(ResumableSource[Rapid7InsightvmSourceConfig, Rapid7InsightvmResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAPID7INSIGHTVM

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "Rapid7 InsightVM rejected the API key. Generate a new Insight Platform key "
            "(Settings → API Keys at insight.rapid7.com), confirm the selected region, then reconnect."
        )
        return {
            "401 Client Error: Unauthorized": message,
            "403 Client Error: Forbidden": message,
        }

    def get_schemas(
        self,
        config: Rapid7InsightvmSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_append,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint.name, []),
            )
            for endpoint in RAPID7_INSIGHTVM_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: Rapid7InsightvmSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_rapid7_insightvm_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[Rapid7InsightvmResumeConfig]:
        return ResumableSourceManager[Rapid7InsightvmResumeConfig](inputs, Rapid7InsightvmResumeConfig)

    def source_for_pipeline(
        self,
        config: Rapid7InsightvmSourceConfig,
        resumable_source_manager: ResumableSourceManager[Rapid7InsightvmResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return rapid7_insightvm_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RAPID7_INSIGHTVM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Rapid7 InsightVM",
            caption=(
                "Connect Rapid7 InsightVM with an **Insight Platform API key** to pull your asset inventory "
                "and vulnerability findings into the PostHog Data warehouse.\n\n"
                "Generate a key under **Settings → API Keys** at [insight.rapid7.com](https://insight.rapid7.com), "
                "then pick the **region** your Insight Platform account lives in (the first part of your product "
                "URL, e.g. `us` in `us.idr.insight.rapid7.com`).\n\n"
                "Requires a paid InsightVM Cloud (Insight Platform) subscription."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/rapid7-insightvm",
            iconPath="/static/services/rapid7_insightvm.png",
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
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="United States (us)", value="us"),
                            SourceFieldSelectConfigOption(label="Europe (eu)", value="eu"),
                            SourceFieldSelectConfigOption(label="Canada (ca)", value="ca"),
                            SourceFieldSelectConfigOption(label="Australia (au)", value="au"),
                            SourceFieldSelectConfigOption(label="Asia Pacific (ap)", value="ap"),
                            SourceFieldSelectConfigOption(label="Japan (jp)", value="jp"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
