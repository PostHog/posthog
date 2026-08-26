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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.waydev import WaydevSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.waydev import (
    WaydevResumeConfig,
    validate_credentials as validate_waydev_credentials,
    waydev_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WaydevSource(ResumableSource[WaydevSourceConfig, WaydevResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.waydev.co/reference/getting-started-with-your-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WAYDEV

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Waydev API token is invalid or expired. Generate a new token in "
            "Waydev under Studio > Waydev API and reconnect.",
            "Unauthorized": "Your Waydev API token is invalid or expired. Generate a new token in "
            "Waydev under Studio > Waydev API and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WaydevSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: WaydevSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_waydev_credentials(config.api_key)
        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Waydev API token"
        return False, "Could not connect to Waydev with the provided API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WaydevResumeConfig]:
        return ResumableSourceManager[WaydevResumeConfig](inputs, WaydevResumeConfig)

    def source_for_pipeline(
        self,
        config: WaydevSourceConfig,
        resumable_source_manager: ResumableSourceManager[WaydevResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = waydev_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=["id"],
            column_hints=resource.column_hints,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WAYDEV,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Waydev",
            caption="Enter the personal access token generated in Waydev under Studio > Waydev API.",
            docsUrl="https://posthog.com/docs/cdp/sources/waydev",
            iconPath="/static/services/waydev.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["dora"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
