from datetime import date
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

from products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably import (
    ABLY_VERSION_2,
    AblyResumeConfig,
    ably_source,
    validate_credentials as validate_ably_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ably.settings import (
    DEFAULT_STATS_UNIT,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTITION_KEY,
    PRIMARY_KEYS,
    STATS_UNITS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    UNVERSIONED_API_VERSION,
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ably import AblySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AblySource(ResumableSource[AblySourceConfig, AblyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://ably.com/docs/api/rest-api"

    supported_versions = (UNVERSIONED_API_VERSION, ABLY_VERSION_2)
    default_version = ABLY_VERSION_2
    deprecated_versions = (VersionDeprecation(version=UNVERSIONED_API_VERSION, sunset_at=date(2025, 11, 1)),)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ABLY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Ably authentication failed. Please check your API key.",
            "403 Client Error": "Ably authentication failed. Please check your API key.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ably.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AblySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The endpoint catalog (`/stats`) and its shape are identical across Ably protocol
        # versions, so discovery is version-independent — the pin is consumed at the request layer.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: AblySourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        # Pre-creation calls pass no pin and resolve to `default_version` (what new rows are
        # stamped with); a pinned source revalidates under its own `X-Ably-Version` header.
        return validate_ably_credentials(config.api_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AblyResumeConfig]:
        return ResumableSourceManager[AblyResumeConfig](inputs, AblyResumeConfig)

    def source_for_pipeline(
        self,
        config: AblySourceConfig,
        resumable_source_manager: ResumableSourceManager[AblyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = ably_source(
            api_key=config.api_key,
            unit=config.unit,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=PRIMARY_KEYS.get(inputs.schema_name, ["id"]),
            column_hints=resource.column_hints,
            partition_mode="datetime",
            partition_keys=[PARTITION_KEY],
            sort_mode="asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ABLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["realtime", "pubsub", "messaging"],
            label="Ably",
            caption="Enter your Ably app API key, created in the [Ably dashboard](https://ably.com/dashboard). "
            "The key must include both the key ID and secret (`app-id.key-id:key-secret`).",
            docsUrl="https://posthog.com/docs/cdp/sources/ably",
            iconPath="/static/services/ably.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="xVLyHw.XXXXXX:1234567890abcdef1234567890abcdef12345678",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="unit",
                        label="Stats granularity",
                        required=True,
                        defaultValue=DEFAULT_STATS_UNIT,
                        options=[SourceFieldSelectConfigOption(label=unit.title(), value=unit) for unit in STATS_UNITS],
                    ),
                ],
            ),
        )
