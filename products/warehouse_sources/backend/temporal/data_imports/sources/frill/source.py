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
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.frill import (
    FrillResumeConfig,
    frill_source,
    validate_credentials as validate_frill_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FrillSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FrillSource(ResumableSource[FrillSourceConfig, FrillResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developers.frill.co/api/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRILL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRILL,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Frill",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Frill API key to sync your Frill ideas, votes, comments, and announcements into the PostHog Data warehouse.

Find your API key under **Settings → Company** in your [Frill dashboard](https://app.frill.co/settings/company).""",
            iconPath="/static/services/frill.png",
            docsUrl="https://posthog.com/docs/cdp/sources/frill",
            keywords=["feedback", "roadmap"],
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
            "Your Frill API key is invalid or has been revoked. Find your API key in your Frill "
            "admin dashboard, then reconnect."
        )
        return {
            # Match on the stable host, not the per-request path/params.
            "401 Client Error: Unauthorized for url: https://api.frill.co": invalid_key_message,
            "403 Client Error: Forbidden for url: https://api.frill.co": invalid_key_message,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.frill.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FrillSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # No Frill list endpoint exposes a server-side updated-since filter, so every stream is
        # full refresh only — neither incremental nor append is offered.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: FrillSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if validate_frill_credentials(config.api_key):
            return True, None

        return False, "Invalid Frill API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FrillResumeConfig]:
        return ResumableSourceManager[FrillResumeConfig](inputs, FrillResumeConfig)

    def source_for_pipeline(
        self,
        config: FrillSourceConfig,
        resumable_source_manager: ResumableSourceManager[FrillResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return frill_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
