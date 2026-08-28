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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opencorporates import (
    OpencorporatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.opencorporates import (
    OpencorporatesResumeConfig,
    opencorporates_source,
    validate_credentials as validate_opencorporates_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpencorporatesSource(ResumableSource[OpencorporatesSourceConfig, OpencorporatesResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v0.4",)
    default_version = "v0.4"
    api_docs_url = "https://api.opencorporates.com/documentation/API-Reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENCORPORATES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPENCORPORATES,
            category=DataWarehouseSourceCategory.CRM,
            label="OpenCorporates",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your OpenCorporates API token and a search term to pull matching company and officer records into the PostHog Data warehouse.

Get an API token from [OpenCorporates](https://opencorporates.com/api_accounts/new). The free open-data tier is limited to around 50 requests a day and 200 a month, so scope your search with a jurisdiction to stay within it.""",
            iconPath="/static/services/opencorporates.png",
            docsUrl="https://posthog.com/docs/cdp/sources/opencorporates",
            keywords=["company registry", "kyb", "firmographics"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="query",
                        label="Search term",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Acme",
                        secret=False,
                        caption="OpenCorporates is a search API, not a full export — this matches against company and officer names.",
                    ),
                    SourceFieldInputConfig(
                        name="jurisdiction_code",
                        label="Jurisdiction code (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="gb",
                        secret=False,
                        caption="Restrict the search to one jurisdiction, e.g. `gb` or `us_de`. Leave blank to search all jurisdictions.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when the REST client calls `raise_for_status()`.
            # OpenCorporates uses 403 (not 429) for rate limiting, so the transport's automatic
            # 429/5xx retries never see it — treat it as terminal-for-this-run rather than retrying
            # blindly through the rest of a monthly quota.
            "401 Client Error: Unauthorized": "Your OpenCorporates API token is invalid or has been revoked. Check the token, then reconnect.",
            "403 Client Error: Forbidden": "Your OpenCorporates account has hit its request quota. Wait for it to reset, narrow your search, or upgrade your plan, then resync.",
        }

    def get_schemas(
        self,
        config: OpencorporatesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OpencorporatesSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_opencorporates_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpencorporatesResumeConfig]:
        return ResumableSourceManager[OpencorporatesResumeConfig](inputs, OpencorporatesResumeConfig)

    def source_for_pipeline(
        self,
        config: OpencorporatesSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpencorporatesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return opencorporates_source(
            api_token=config.api_token,
            query=config.query,
            jurisdiction_code=config.jurisdiction_code,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
