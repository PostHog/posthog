from typing import cast

from requests import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.frontegg import (
    FronteggAuth,
    FronteggResumeConfig,
    frontegg_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
    REGION_ERROR,
    REGIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frontegg import (
    FronteggSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FronteggSource(ResumableSource[FronteggSourceConfig, FronteggResumeConfig]):
    lists_tables_without_credentials = True
    # The pin selects the users API; roles and permissions have independent endpoint versions.
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developers.frontegg.com/ciam/api/identity"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRONTEGG

    @property
    def connection_host_fields(self) -> list[str]:
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "400 Client Error": AUTH_ERROR,
            "[oauth2_token_config_error]": AUTH_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FronteggSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: FronteggSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.region not in REGIONS:
            return False, REGION_ERROR
        try:
            FronteggAuth(config)._obtain_token(timeout=(5, 10))
        except OAuth2AuthRequestError:
            return False, AUTH_ERROR
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status in (400, 401):
                return False, AUTH_ERROR
            if status == 403:
                return False, PERMISSION_ERROR
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FronteggResumeConfig]:
        return ResumableSourceManager(inputs, FronteggResumeConfig)

    def source_for_pipeline(
        self,
        config: FronteggSourceConfig,
        resumable_source_manager: ResumableSourceManager[FronteggResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return frontegg_source(config, resumable_source_manager, inputs, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FRONTEGG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Frontegg",
            caption="Find your client ID and API key in your Frontegg environment under Keys & domains.",
            iconPath="/static/services/frontegg.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        defaultValue="EU",
                        required=True,
                        options=[SourceFieldSelectConfigOption(label=region, value=region) for region in REGIONS],
                    ),
                ],
            ),
        )
