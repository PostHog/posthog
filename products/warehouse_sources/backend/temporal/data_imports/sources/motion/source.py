from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motion import MotionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.motion import (
    MotionResumeConfig,
    motion_source,
    validate_credentials as validate_motion_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MotionSource(ResumableSource[MotionSourceConfig, MotionResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.usemotion.com/api-reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOTION

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.usemotion.com": "Motion rejected this API key. Create a new key in Motion under Settings and reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.usemotion.com": "This Motion API key does not have access to the requested data.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MOTION,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Motion",
            caption="""Enter your Motion API key to sync your workspaces, users, projects, and tasks into the PostHog Data warehouse.

Create an API key in Motion under Settings, then API. Motion shows the key once, so copy it before closing the dialog.

Motion rate limits API keys, and individual accounts get a much smaller allowance than teams, so a first sync of a large workspace can take a while.""",
            iconPath="/static/services/motion.png",
            docsUrl="https://posthog.com/docs/cdp/sources/motion",
            keywords=["usemotion", "calendar", "tasks"],
            releaseStatus=ReleaseStatus.ALPHA,
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
                        caption="Create this in Motion under Settings, then API.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.motion.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MotionSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MotionSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_motion_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MotionResumeConfig]:
        return ResumableSourceManager[MotionResumeConfig](inputs, MotionResumeConfig)

    def source_for_pipeline(
        self,
        config: MotionSourceConfig,
        resumable_source_manager: ResumableSourceManager[MotionResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Motion endpoint: {inputs.schema_name}")

        return motion_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=None,
        )
