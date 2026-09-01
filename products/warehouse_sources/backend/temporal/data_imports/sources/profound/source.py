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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.profound import (
    ProfoundSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound import (
    ProfoundResumeConfig,
    profound_source,
    validate_credentials as validate_profound_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ProfoundSource(ResumableSource[ProfoundSourceConfig, ProfoundResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Profound versions purely by URL path segment (`/v1/...`, `/v2/...`) — no version header or
    # account setting. The source already reads the newer v2 report surface (`/v2/reports/*`)
    # alongside the org lists that only exist under `/v1/`, so the label is a pin recorded on the
    # source, not a request-layer branch: every version resolves to the same requests (see
    # settings.py). v2 is the default so new sources record the surface they actually sync.
    supported_versions = ("v1", "v2")
    default_version = "v2"
    api_docs_url = "https://docs.tryprofound.com/rest-api/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROFOUND

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PROFOUND,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Profound",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Profound answer engine data into the PostHog Data warehouse, so you can join brand visibility and citations to your product and web analytics.

Create an API key under **Settings** then **API keys** in Profound. The API is available on Enterprise plans, and Profound has to enable it for your organization first.""",
            iconPath="/static/services/profound.png",
            docsUrl="https://posthog.com/docs/cdp/sources/profound",
            keywords=["aeo", "geo", "answer engine", "ai search", "brand visibility"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.profound.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.tryprofound.com": "Your Profound API key is invalid or has been revoked. Create a new key in Profound, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.tryprofound.com": "Your Profound organization does not have API access. The API is an Enterprise feature that Profound has to enable, so contact their support and then reconnect.",
        }

    def get_schemas(
        self,
        config: ProfoundSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only the two report tables carry incremental fields; the reference lists have no time
        # filter and stay full refresh.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ProfoundSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_profound_credentials(config.api_key):
            return True, None

        return (
            False,
            "Profound rejected this API key. Check the key, and confirm your organization has API access enabled.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ProfoundResumeConfig]:
        return ResumableSourceManager[ProfoundResumeConfig](inputs, ProfoundResumeConfig)

    def source_for_pipeline(
        self,
        config: ProfoundSourceConfig,
        resumable_source_manager: ResumableSourceManager[ProfoundResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return profound_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
