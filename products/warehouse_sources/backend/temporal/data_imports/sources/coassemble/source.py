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
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.coassemble import (
    CoassembleResumeConfig,
    coassemble_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.settings import (
    COASSEMBLE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoassembleSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoassembleSource(ResumableSource[CoassembleSourceConfig, CoassembleResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COASSEMBLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COASSEMBLE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Coassemble",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["lms", "training", "courses"],
            caption="""Enter your Coassemble workspace ID and API key to pull your courses, collections, learners, and learner progress into the PostHog Data warehouse.

You can generate an API key from your workspace API settings in [Coassemble](https://coassemble.com). API access must be enabled on your workspace plan.
""",
            iconPath="/static/services/coassemble.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coassemble",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.coassemble.com": "Your Coassemble workspace ID or API key is invalid or has been regenerated. Generate a new key in your workspace API settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.coassemble.com": "Your Coassemble API key does not have access to this data. Check that API access is enabled on your workspace plan, then reconnect.",
        }

    def get_schemas(
        self,
        config: CoassembleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — see the rationale in settings.py.
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
        self, config: CoassembleSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is workspace-wide, so a single probe validates access to every schema.
        return validate_credentials(config.workspace_id, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CoassembleResumeConfig]:
        return ResumableSourceManager[CoassembleResumeConfig](inputs, CoassembleResumeConfig)

    def source_for_pipeline(
        self,
        config: CoassembleSourceConfig,
        resumable_source_manager: ResumableSourceManager[CoassembleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in COASSEMBLE_ENDPOINTS:
            raise ValueError(f"Unknown Coassemble schema '{inputs.schema_name}'")

        return coassemble_source(
            workspace_id=config.workspace_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
