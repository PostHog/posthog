from typing import cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.telli import TelliSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.telli import (
    TelliResumeConfig,
    telli_source,
    validate_credentials as validate_telli_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

AUTH_ERRORS = {
    401: "Your telli API key is invalid or expired. Create a new key in Settings > Developer and reconnect.",
    402: "API access requires a paid telli plan. Check your telli subscription and try again.",
    403: "Your telli API key does not have permission to access this data. Check its permissions and try again.",
}


@SourceRegistry.register
class TelliSource(ResumableSource[TelliSourceConfig, TelliResumeConfig]):
    lists_tables_without_credentials = True
    # Calls and phone numbers remain on v1; telli only provides their list endpoints there.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.telli.com/api-getting-started"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TELLI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{status} Client Error": message for status, message in AUTH_ERRORS.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.telli.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TelliSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TelliSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            validate_telli_credentials(config.api_key, schema_name)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status is not None and status in AUTH_ERRORS:
                return False, AUTH_ERRORS[status]
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TelliResumeConfig]:
        return ResumableSourceManager(inputs, TelliResumeConfig)

    def source_for_pipeline(
        self,
        config: TelliSourceConfig,
        resumable_source_manager: ResumableSourceManager[TelliResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return telli_source(config.api_key, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TELLI,
            category=DataWarehouseSourceCategory.SALES,
            label="telli",
            caption="Enter an API key from telli Settings > Developer. API access requires a paid telli plan.",
            docsUrl="https://posthog.com/docs/cdp/sources/telli",
            iconPath="/static/services/telli.png",
            keywords=["voice", "calls", "dialer", "contacts"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        placeholder="Enter your telli API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
