from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.transistor import (
    TransistorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TRANSISTOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.transistor import (
    TransistorResumeConfig,
    transistor_source,
    validate_credentials as validate_transistor_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TransistorSource(ResumableSource[TransistorSourceConfig, TransistorResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # `/v1` is the only path Transistor has ever published and is not a documented version
    # choice, so the source stays on the framework's unversioned default.
    api_docs_url = "https://developers.transistor.fm/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRANSISTOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRANSISTOR,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Transistor.fm",
            keywords=["podcast", "transistor fm"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your shows, episodes, private podcast subscribers, and daily download analytics from [Transistor](https://transistor.fm) into the PostHog Data warehouse.

Create an API key in your Transistor account settings, then paste it below. The key has access to every show your Transistor user can see.

Download analytics sync incrementally by day. The other tables sync as a full refresh.""",
            iconPath="/static/services/transistor.png",
            docsUrl="https://posthog.com/docs/cdp/sources/transistor",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Transistor rejected the API key. Generate a new key in your Transistor account settings and reconnect.",
            "403 Client Error: Forbidden for url": "This Transistor API key does not have access to the requested show. Check the key's account permissions and reconnect.",
        }

    def get_schemas(
        self,
        config: TransistorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=TRANSISTOR_ENDPOINTS[endpoint].supports_incremental,
                supports_append=TRANSISTOR_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=TRANSISTOR_ENDPOINTS[endpoint].description,
                default_incremental_lookback_seconds=TRANSISTOR_ENDPOINTS[
                    endpoint
                ].default_incremental_lookback_seconds,
                detected_primary_keys=list(TRANSISTOR_ENDPOINTS[endpoint].primary_keys),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: TransistorSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_transistor_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TransistorResumeConfig]:
        return ResumableSourceManager[TransistorResumeConfig](inputs, TransistorResumeConfig)

    def source_for_pipeline(
        self,
        config: TransistorSourceConfig,
        resumable_source_manager: ResumableSourceManager[TransistorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return transistor_source(
            endpoint=inputs.schema_name,
            api_key=config.api_key,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
