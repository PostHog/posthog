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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HuntrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.huntr import (
    HuntrResumeConfig,
    huntr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.settings import ENDPOINTS, HUNTR_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HuntrSource(ResumableSource[HuntrSourceConfig, HuntrResumeConfig]):
    api_docs_url = "https://docs.huntr.co"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HUNTR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HUNTR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Huntr",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Huntr organization access token to pull your Organization API data into the PostHog Data warehouse.

You can generate an access token in your Huntr organization admin dashboard. The token grants read access to your members, advisors, candidates, jobs, job posts, employers, activities, and actions.
""",
            iconPath="/static/services/huntr.png",
            docsUrl="https://posthog.com/docs/cdp/sources/huntr",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Organization access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.huntr.co/org": "Your Huntr access token is invalid or has been revoked. Generate a new token in your Huntr organization admin dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.huntr.co/org": "Your Huntr access token does not have access to this data. Check the token's permissions in your organization admin dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: HuntrSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — only Huntr's jobs endpoint exposes a documented
        # created_after/created_before filter, and no resource exposes a reliable updated_after
        # cursor, so there is no incremental cursor to advance across every stream.
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
        self, config: HuntrSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The access token is organization-wide, so a single probe validates access to every schema.
        return validate_credentials(config.access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HuntrResumeConfig]:
        return ResumableSourceManager[HuntrResumeConfig](inputs, HuntrResumeConfig)

    def source_for_pipeline(
        self,
        config: HuntrSourceConfig,
        resumable_source_manager: ResumableSourceManager[HuntrResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in HUNTR_ENDPOINTS:
            raise ValueError(f"Unknown Huntr schema '{inputs.schema_name}'")

        return huntr_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
