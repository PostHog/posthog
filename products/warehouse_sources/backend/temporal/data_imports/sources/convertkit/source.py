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
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit import (
    ConvertKitResumeConfig,
    convertkit_source,
    validate_credentials as validate_convertkit_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.settings import (
    CONVERTKIT_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConvertKitSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConvertKitSource(ResumableSource[ConvertKitSourceConfig, ConvertKitResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://developers.kit.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONVERTKIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONVERT_KIT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["kit"],
            label="ConvertKit",
            caption="""Enter your Kit (formerly ConvertKit) API key to pull your Kit data into the PostHog Data warehouse.

You can create a v4 API key in your [Kit account settings](https://app.kit.com/account_settings/developer_settings).""",
            iconPath="/static/services/convertkit.png",
            docsUrl="https://posthog.com/docs/cdp/sources/convertkit",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="kit_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ConvertKitSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=endpoint_config.incremental_fields,
            )
            for endpoint_config in (CONVERTKIT_ENDPOINTS[name] for name in ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ConvertKitSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_convertkit_credentials(config.api_key, schema_name)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.kit.com": "Your Kit API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.kit.com": "Your Kit API key does not have the required permissions. Please check the key and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ConvertKitResumeConfig]:
        return ResumableSourceManager[ConvertKitResumeConfig](inputs, ConvertKitResumeConfig)

    def source_for_pipeline(
        self,
        config: ConvertKitSourceConfig,
        resumable_source_manager: ResumableSourceManager[ConvertKitResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return convertkit_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
