from typing import cast

from requests import RequestException

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.serpstat import (
    SerpstatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.serpstat import (
    SerpstatResumeConfig,
    serpstat_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.settings import (
    AUTH_ERROR,
    DOCS_BASE,
    ENDPOINTS,
    QUOTA_ERROR,
    REQUEST_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SerpstatSource(ResumableSource[SerpstatSourceConfig, SerpstatResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = f"{DOCS_BASE}jenasqbwtxdlr-introduction-to-serpstat-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SERPSTAT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {message: message for message in (AUTH_ERROR, QUOTA_ERROR, REQUEST_ERROR)}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SerpstatSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                detected_primary_keys=list(endpoint.primary_keys),
                description=CANONICAL_DESCRIPTIONS[name]["description"],
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: SerpstatSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        for label, value in (("project ID", config.project_id), ("project region ID", config.project_region_id)):
            try:
                if int(value) <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                return False, f"Enter a positive integer for the Serpstat {label}."
        try:
            list(
                serpstat_resource(
                    config, "projects", team_id, "", self.resolve_api_version(api_version), credential_check=True
                )
            )
        except ValueError as error:
            message = str(error)
            return False, message if message in self.get_non_retryable_errors() else REQUEST_ERROR
        except (RequestException, RESTClientRetryableError):
            return False, "Could not reach Serpstat. Try again later."
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SerpstatResumeConfig]:
        return ResumableSourceManager(inputs, SerpstatResumeConfig)

    def source_for_pipeline(
        self,
        config: SerpstatSourceConfig,
        resumable_source_manager: ResumableSourceManager[SerpstatResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = ENDPOINTS[inputs.schema_name]
        resource = serpstat_resource(
            config,
            inputs.schema_name,
            inputs.team_id,
            inputs.job_id,
            self.resolve_api_version(inputs.api_version),
            resumable_source_manager,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=list(endpoint.primary_keys),
            partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
            partition_mode="datetime" if endpoint.partition_key else None,
            partition_format="month" if endpoint.partition_key else None,
            sort_mode="asc" if inputs.schema_name in ("project_keywords", "project_positions") else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SERPSTAT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Serpstat",
            iconPath="/static/services/serpstat.png",
            docsUrl="https://posthog.com/docs/cdp/sources/serpstat",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Create an API token on your [Serpstat profile](https://serpstat.com/users/profile/). "
                "API access requires the Team plan or higher. "
                "Syncs use your account's API units when Serpstat applies a charge. "
                "Serpstat lists these methods as free of API credit charges. "
                "Paginated tables include up to 500 records. Positions cover the last seven days for one project region."
            ),
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
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                        caption="Copy the project ID from the URL of your Serpstat Rank Tracker report.",
                    ),
                    SourceFieldInputConfig(
                        name="project_region_id",
                        label="Project region ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                        caption="Use the region ID from the Serpstat getProjectRegions method.",
                    ),
                ],
            ),
        )
