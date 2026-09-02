from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loopreturns import (
    LoopReturnsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.loop_returns import (
    API_VERSION_2026_07,
    API_VERSION_V1,
    LoopReturnsResumeConfig,
    endpoint_permissions,
    loop_returns_source,
    start_date_error,
    validate_credentials as validate_loop_returns_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LoopReturnsSource(ResumableSource[LoopReturnsSourceConfig, LoopReturnsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # Loop versions its API by date in the URL path (`/api/2026-07/...`). `v1` is a legacy alias
    # for the `2026-07` GA release that Loop is phasing out, so new sources pin the explicit date
    # version and `v1` is marked deprecated. No calendar sunset date is published for the alias.
    supported_versions = (API_VERSION_V1, API_VERSION_2026_07)
    default_version = API_VERSION_2026_07
    deprecated_versions = (VersionDeprecation(version=API_VERSION_V1, sunset_at=None),)
    api_docs_url = "https://docs.loopreturns.com/api-reference/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOOPRETURNS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LOOP_RETURNS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Loop Returns",
            releaseStatus=ReleaseStatus.ALPHA,
            docsUrl="https://posthog.com/docs/cdp/sources/loop-returns",
            caption="""Enter your Loop API key to pull your returns data into the PostHog Data warehouse.

Create a key in Loop under **Settings** > **Developers**. The key needs the `Returns` scope for the returns and advanced shipping notice tables, and `Destinations (Read)` for the destinations table.

Start date is optional and sets how far back the first sync reaches. Without it, syncing starts two years ago.""",
            iconPath="/static/services/loop_returns.png",
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
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.loopreturns.com": "Loop rejected your API key. Check that the key is still active and has the scope this table needs, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.loopreturns.com": "Your Loop API key does not have permission to read this table. Add the required scope to the key and reconnect.",
        }

    def get_schemas(
        self,
        config: LoopReturnsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: LoopReturnsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.start_date:
            error = start_date_error(config.start_date)
            if error is not None:
                return False, error

        return validate_loop_returns_credentials(
            config.api_key, self.resolve_api_version(api_version), schema_name=schema_name
        )

    def get_endpoint_permissions(
        self,
        config: LoopReturnsSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return endpoint_permissions(config.api_key, self.resolve_api_version(api_version), endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LoopReturnsResumeConfig]:
        return ResumableSourceManager[LoopReturnsResumeConfig](inputs, LoopReturnsResumeConfig)

    def source_for_pipeline(
        self,
        config: LoopReturnsSourceConfig,
        resumable_source_manager: ResumableSourceManager[LoopReturnsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return loop_returns_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            start_date=config.start_date,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
