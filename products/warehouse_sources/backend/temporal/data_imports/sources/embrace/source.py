from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.embrace.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.embrace.embrace import (
    EmbraceResumeConfig,
    embrace_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.embrace.settings import (
    API_DOCS_URL,
    AUTH_ERRORS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.embrace import (
    EmbraceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EmbraceSource(ResumableSource[EmbraceSourceConfig, EmbraceResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EMBRACE

    @property
    def connection_host_fields(self) -> list[str]:
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERRORS[401],
            "403 Client Error": AUTH_ERRORS[403],
            "Unsupported Embrace API version": "Unsupported Embrace API version. Select v1.",
            "Invalid Embrace region": "Invalid Embrace region. Select a region from the list.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: EmbraceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self, config: EmbraceSourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, schema_name or "sessions", self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EmbraceResumeConfig]:
        return ResumableSourceManager(inputs, EmbraceResumeConfig)

    def source_for_pipeline(
        self,
        config: EmbraceSourceConfig,
        resumable_source_manager: ResumableSourceManager[EmbraceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return embrace_source(
            config=config,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            manager=resumable_source_manager,
            last_value=inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EMBRACE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Embrace (Embrace.io)",
            iconPath="/static/services/embrace.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Get your Metrics API token from Embrace Settings > Organization > API. "
            "Imports cover the latest 30 days of hourly metrics, with a one-hour delay. "
            "Incremental syncs retain older imported rows. Full refresh replaces them with the latest 30 days.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Metrics API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Embrace app ID",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="default",
                        options=[
                            SourceFieldSelectConfigOption(label="Default (api.embrace.io)", value="default"),
                            SourceFieldSelectConfigOption(label="United States (US1)", value="us"),
                            SourceFieldSelectConfigOption(label="European Union (EU1)", value="eu"),
                        ],
                    ),
                ],
            ),
        )
