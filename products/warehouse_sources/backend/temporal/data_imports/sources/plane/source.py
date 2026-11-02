from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plane import PlaneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plane.plane import (
    INVALID_KEY_MESSAGE,
    PERMISSION_MESSAGE,
    WORKSPACE_MESSAGE,
    PlaneResumeConfig,
    hostname_of,
    plane_source,
    probe_workspace,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plane.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlaneSource(ResumableSource[PlaneSourceConfig, PlaneResumeConfig], ValidateDatabaseHostMixin):
    codebase_detection = detect(
        env=("^PLANE_API_KEY$",),
        npm=("@makeplane/plane-node-sdk",),
        pypi=("plane-sdk",),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.plane.so/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLANE

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key goes to `base_url`; pointing it elsewhere must require the key again.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PLANE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Plane",
            keywords=["plane.so", "project management", "issues"],
            caption="""Sync projects, work items, cycles and modules from a Plane workspace.

Create a personal access token in Plane under **Profile settings > Personal access tokens**. The token reads everything its owner can see. The workspace slug is the part after the domain in your Plane URL, for example `my-team` in `app.plane.so/my-team`. Leave the instance URL blank for Plane Cloud. A self-hosted instance must be reachable over https and run a release with the v2 API.""",
            iconPath="/static/services/plane.png",
            docsUrl="https://posthog.com/docs/cdp/sources/plane",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="plane_api_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_slug",
                        label="Workspace slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-team",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Instance URL",
                        caption="Only for a self-hosted Plane. Leave blank for Plane Cloud.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://plane.example.com",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_KEY_MESSAGE,
            "403 Client Error": PERMISSION_MESSAGE,
            "402 Client Error": "This Plane workspace's plan doesn't include the feature this table reads. Turn the table off, or upgrade the Plane plan.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.plane.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PlaneSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()},
        )

    def _host_error(self, config: PlaneSourceConfig, team_id: int) -> str | None:
        try:
            hostname = hostname_of(config.base_url)
        except ValueError as error:
            return str(error)
        valid, host_error = self.is_database_host_valid(hostname, team_id)
        return None if valid else host_error

    def validate_credentials(
        self,
        config: PlaneSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        host_error = self._host_error(config, team_id)
        if host_error:
            return False, host_error
        try:
            status = probe_workspace(config.base_url, config.api_key, config.workspace_slug)
        except ValueError as error:
            return False, str(error)
        if status == 200:
            return True, None
        if status == 401:
            return False, INVALID_KEY_MESSAGE
        if status == 403:
            return False, PERMISSION_MESSAGE
        if status == 404:
            return False, WORKSPACE_MESSAGE
        return False, "Couldn't reach Plane to check the API key. Check the instance URL, then try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlaneResumeConfig]:
        return ResumableSourceManager[PlaneResumeConfig](inputs, PlaneResumeConfig)

    def source_for_pipeline(
        self,
        config: PlaneSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlaneResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_error = self._host_error(config, inputs.team_id)
        if host_error:
            raise ValueError(host_error)
        return plane_source(config.base_url, config.api_key, config.workspace_slug, inputs, resumable_source_manager)
