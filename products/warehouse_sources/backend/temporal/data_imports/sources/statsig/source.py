from typing import cast

from requests import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statsig import (
    StatsigSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.settings import API_VERSION, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.statsig import (
    StatsigResumeConfig,
    probe_credentials,
    statsig_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StatsigSource(ResumableSource[StatsigSourceConfig, StatsigResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.statsig.com/console-api/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STATSIG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STATSIG,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Statsig",
            caption="Enter a Console API key from [Statsig Project Settings](https://console.statsig.com/api_keys). "
            "The key needs read access to the tables you select. The users table contains project members.",
            docsUrl="https://posthog.com/docs/cdp/sources/statsig",
            iconPath="/static/services/statsig.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Console API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: StatsigSourceConfig,
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
                detected_primary_keys=[endpoint.primary_key],
                description=CANONICAL_DESCRIPTIONS[name]["description"],
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: StatsigSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This Statsig table is not supported. Select a table from the source configuration."
        endpoint = ENDPOINTS[schema_name or "gates"]
        try:
            probe_credentials(config.api_key, endpoint.path, self.resolve_api_version(api_version))
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, "Statsig rejected your API key. Enter a valid Console API key and reconnect the source."
            if status == 403:
                if schema_name is None:
                    return True, None
                return False, "Your Console API key cannot read this table. Give the key read access in Statsig."
            raise
        return True, None

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Statsig rejected your API key. Enter a valid Console API key and reconnect the source.",
            "403 Client Error": "Your Console API key cannot read this table. Give the key read access in Statsig.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StatsigResumeConfig]:
        return ResumableSourceManager(inputs, StatsigResumeConfig)

    def source_for_pipeline(
        self,
        config: StatsigSourceConfig,
        resumable_source_manager: ResumableSourceManager[StatsigResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return statsig_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
