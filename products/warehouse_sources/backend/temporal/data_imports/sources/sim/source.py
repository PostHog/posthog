from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sim import SimSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.sim.sim import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    WORKSPACE_ERROR,
    SimResumeConfig,
    sim_source,
    validate_credentials as validate_sim_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SimSource(ResumableSource[SimSourceConfig, SimResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.sim.ai/api-reference/getting-started"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error:": AUTH_ERROR,
            "403 Client Error:": PERMISSION_ERROR,
            "404 Client Error:": WORKSPACE_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: SimSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown Sim table: {schema_name}. Select workflows or logs."
        return validate_sim_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_schemas(
        self,
        config: SimSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SimResumeConfig]:
        return ResumableSourceManager(inputs, SimResumeConfig)

    def source_for_pipeline(
        self,
        config: SimSourceConfig,
        resumable_source_manager: ResumableSourceManager[SimResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sim_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Sim",
            iconPath="/static/services/sim.png",
            keywords=["ai agents", "workflow", "automation", "logs"],
            docsUrl="https://posthog.com/docs/cdp/sources/sim",
            caption="Create a personal or workspace API key in Sim settings with read access to the workspace. "
            "Find the workspace ID in the URL: `https://www.sim.ai/workspace/{workspaceId}/w/{workflowId}`.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        placeholder="",
                        required=True,
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
