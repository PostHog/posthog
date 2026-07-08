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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RecruiteeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.recruitee import (
    RecruiteeResumeConfig,
    recruitee_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.settings import (
    ENDPOINTS,
    RECRUITEE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RecruiteeSource(ResumableSource[RecruiteeSourceConfig, RecruiteeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RECRUITEE

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to api.recruitee.com/c/<company_id>, so retargeting the company ID
        # must re-require the token — otherwise a preserved token could be pointed at another company.
        return ["company_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RECRUITEE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Recruitee",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Recruitee company ID and API token to pull your recruiting data into the PostHog Data warehouse.

Find your company ID and create a personal API token under **Settings → Apps and plugins → Personal API tokens** in [Recruitee](https://app.recruitee.com/). The token grants read access to your candidates, offers, departments, and placements. All tables sync via full refresh.
""",
            iconPath="/static/services/recruitee.png",
            docsUrl="https://posthog.com/docs/cdp/sources/recruitee",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="company_id",
                        label="Company ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.recruitee.com": "Your Recruitee API token is invalid or has been revoked. Generate a new token under Settings → Apps and plugins → Personal API tokens, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.recruitee.com": "Your Recruitee API token does not have access to this data. Check the token's role and permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: RecruiteeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Recruitee's list endpoints expose no documented,
        # reliably ordered server-side timestamp filter, so there is no incremental cursor to advance.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: RecruiteeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The token is company-wide, so a single probe validates access to every schema.
        return validate_credentials(config.company_id, config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RecruiteeResumeConfig]:
        return ResumableSourceManager[RecruiteeResumeConfig](inputs, RecruiteeResumeConfig)

    def source_for_pipeline(
        self,
        config: RecruiteeSourceConfig,
        resumable_source_manager: ResumableSourceManager[RecruiteeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in RECRUITEE_ENDPOINTS:
            raise ValueError(f"Unknown Recruitee schema '{inputs.schema_name}'")

        return recruitee_source(
            company_id=config.company_id,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
