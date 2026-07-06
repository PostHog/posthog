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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TeamtailorSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.settings import (
    ENDPOINTS,
    TEAMTAILOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.teamtailor import (
    TeamtailorResumeConfig,
    check_access,
    teamtailor_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TeamtailorSource(ResumableSource[TeamtailorSourceConfig, TeamtailorResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEAMTAILOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEAMTAILOR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Teamtailor",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Teamtailor API key to pull your recruiting data into the PostHog Data warehouse.

You can create an API key under **Settings → API keys** in Teamtailor. The key grants read access to your candidates, jobs, job applications, users, and departments.
""",
            iconPath="/static/services/teamtailor.png",
            docsUrl="https://posthog.com/docs/cdp/sources/teamtailor",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.teamtailor.com": "Your Teamtailor API key is invalid or has been revoked. Generate a new key under Settings → API keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.teamtailor.com": "Your Teamtailor API key does not have access to this data. Check the key's scope, then reconnect.",
        }

    def get_schemas(
        self,
        config: TeamtailorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Teamtailor's created-at/updated-at filter syntax is
        # under-documented, so there is no incremental cursor we can advance safely.
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
        self, config: TeamtailorSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Teamtailor API key"
        return False, message or "Could not validate Teamtailor API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TeamtailorResumeConfig]:
        return ResumableSourceManager[TeamtailorResumeConfig](inputs, TeamtailorResumeConfig)

    def source_for_pipeline(
        self,
        config: TeamtailorSourceConfig,
        resumable_source_manager: ResumableSourceManager[TeamtailorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in TEAMTAILOR_ENDPOINTS:
            raise ValueError(f"Unknown Teamtailor schema '{inputs.schema_name}'")

        return teamtailor_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
