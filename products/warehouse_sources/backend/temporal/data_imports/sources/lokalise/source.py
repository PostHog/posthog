from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lokalise import (
    LokaliseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lokalise.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lokalise.lokalise import (
    INVALID_TOKEN_MESSAGE,
    PERMISSION_MESSAGE,
    LokaliseResumeConfig,
    lokalise_source,
    validate_lokalise_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lokalise.settings import LOKALISE_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LokaliseSource(ResumableSource[LokaliseSourceConfig, LokaliseResumeConfig]):
    codebase_detection = detect(
        env=("^LOKALISE_",),
        npm=("@lokalise/node-api", "lokalise-file-exchange"),
        pypi=("python-lokalise-api",),
        cocoapods=("Lokalise",),
        composer=("lokalise/php-lokalise-api",),
        go=("github.com/lokalise/go-lokalise-api",),
        hex=("elixir_lokalise_api",),
        maven=("com.lokalise.android:ota-sdk",),
        pub=("lokalise_flutter_sdk",),
        rubygems=("ruby-lokalise-api", "lokalise_rails", "lokalise_manager"),
        swiftpm=("github.com/lokalise/lokalise-ios-framework",),
    )

    lists_tables_without_credentials = True
    supported_versions = ("api2",)
    default_version = "api2"
    api_docs_url = "https://developers.lokalise.com/docs/api-changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOKALISE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOKALISE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Lokalise",
            iconPath="/static/services/lokalise.png",
            docsUrl="https://posthog.com/docs/cdp/sources/lokalise",
            caption="Create a read-only API token in your Lokalise personal profile. The source imports data from accessible projects.",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="Enter your API token",
                    )
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.lokalise.com": INVALID_TOKEN_MESSAGE,
            "403 Client Error: Forbidden for url: https://api.lokalise.com": PERMISSION_MESSAGE,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self, config: LokaliseSourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_lokalise_credentials(config.api_token, self.resolve_api_version(api_version), schema_name)

    def get_schemas(
        self,
        config: LokaliseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            LOKALISE_ENDPOINTS,
            {name: config.incremental_fields for name, config in LOKALISE_ENDPOINTS.items()},
            names,
            descriptions={name: description["description"] for name, description in CANONICAL_DESCRIPTIONS.items()},
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LokaliseResumeConfig]:
        return ResumableSourceManager(inputs, LokaliseResumeConfig)

    def source_for_pipeline(
        self,
        config: LokaliseSourceConfig,
        resumable_source_manager: ResumableSourceManager[LokaliseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lokalise_source(
            api_token=config.api_token,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
