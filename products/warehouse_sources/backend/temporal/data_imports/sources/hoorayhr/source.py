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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hoorayhr import (
    HoorayHRSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.hoorayhr import (
    hoorayhr_source,
    validate_credentials as validate_hoorayhr_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HoorayHRSource(SimpleSource[HoorayHRSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://api.hoorayhr.io/documentation"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOORAYHR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HOORAY_HR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="HoorayHR",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your HoorayHR API key to pull your HR data (users, time off, sick leave, contracts, and more) into the PostHog Data warehouse.

You need the admin role in your HoorayHR company to create an API key: go to [Settings → API keys](https://app.hoorayhr.io/settings/api-keys) and click "New API key". The key (prefixed `pk_`) is shown only once, so copy it right away.""",
            iconPath="/static/services/hoorayhr.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hoorayhr",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your HoorayHR API key is invalid or has been revoked. Create a new key under Settings → API keys in HoorayHR, then reconnect.",
            "403 Client Error": "Your HoorayHR API key is not authorized for this data. API keys act as the user who created them, so make sure that user still has the admin role.",
        }

    def get_schemas(
        self,
        config: HoorayHRSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # HoorayHR's API exposes no pagination, cursors, or server-side timestamp filters, so every
        # table is full refresh only.
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: HoorayHRSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_hoorayhr_credentials(config.api_key):
            return True, None

        return False, "HoorayHR rejected the credentials. Check the API key is correct and hasn't been revoked."

    def source_for_pipeline(self, config: HoorayHRSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return hoorayhr_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
