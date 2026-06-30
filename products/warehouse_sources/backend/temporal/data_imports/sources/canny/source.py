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
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny import (
    CannyResumeConfig,
    canny_source,
    validate_credentials as validate_canny_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.settings import (
    CANNY_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CannySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CannySource(ResumableSource[CannySourceConfig, CannyResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CANNY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CANNY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Canny",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Canny API key to sync your Canny feedback, posts, and roadmap data into the PostHog Data warehouse.

Find your secret API key under **Settings → API** in your Canny dashboard.""",
            iconPath="/static/services/canny.png",
            docsUrl="https://posthog.com/docs/cdp/sources/canny",
            unreleasedSource=True,
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        invalid_key_message = (
            "Your Canny API key is invalid or has been revoked. Find your secret API key under "
            "Settings → API in your Canny dashboard, then reconnect."
        )
        return {
            # Canny reports a bad API key either via an `{"error": ...}` body (raised as an HTTPError
            # carrying the error text) or a 401/403 status. Match the stable host, not the per-request
            # path/params. The exact wording is API-version dependent, so match the broad signals.
            "invalid API key": invalid_key_message,
            "401 Client Error: Unauthorized for url: https://canny.io": invalid_key_message,
            "403 Client Error: Forbidden for url: https://canny.io": invalid_key_message,
        }

    def get_schemas(
        self,
        config: CannySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No Canny list endpoint exposes a server-side updated-since filter, so every stream is
        # full refresh only — neither incremental nor append is offered.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in CANNY_ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CannySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_canny_credentials(config.api_key):
            return True, None

        return False, "Invalid Canny API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CannyResumeConfig]:
        return ResumableSourceManager[CannyResumeConfig](inputs, CannyResumeConfig)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.canny.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def source_for_pipeline(
        self,
        config: CannySourceConfig,
        resumable_source_manager: ResumableSourceManager[CannyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return canny_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
