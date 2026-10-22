from typing import cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.criteo import (
    CriteoClient,
    CriteoResumeConfig,
    criteo_source,
    report_start_date,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.settings import (
    API_VERSION,
    DEFAULT_LOOKBACK_SECONDS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.criteo import CriteoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CriteoSource(ResumableSource[CriteoSourceConfig, CriteoResumeConfig]):
    codebase_detection = detect(
        env=("^CRITEO_",),
        script_hosts=("dynamic.criteo.com", "static.criteo.net"),
        pypi=("criteo-api-marketingsolutions-sdk", "criteo-api-retailmedia-sdk"),
        composer=(
            "criteo/criteo-api-marketingsolutions-sdk",
            "criteo/criteo-api-retailmedia-sdk",
            "criteo/criteo-api-commercegrid-sdk",
            "criteo/criteo-php-marketing-sdk",
            "criteo/criteo-php-marketing-transition-sdk",
        ),
        maven=(
            "com.criteo:criteo-api-marketingsolutions-sdk",
            "com.criteo:criteo-api-retailmedia-sdk",
            "com.criteo:criteo-api-commercegrid-sdk",
            "com.criteo:criteo-api-commercegrid-sdk-experimental",
            "com.criteo:criteo-api-marketingsolutions-sdk-experimental",
            "com.criteo:criteo-api-retailmedia-sdk-experimental",
        ),
    )

    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://developers.criteo.com/criteo-apis/docs/versioning-policy"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRITEO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CRITEO,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Criteo",
            iconPath="/static/services/criteo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/criteo",
            releaseStatus=ReleaseStatus.BETA,
            caption="Use a Marketing Solutions application with client credentials. "
            "Grant advertiser consent and read access to Campaign, Creative, Audience, and Analytics in the Criteo Partners Portal.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Report start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="YYYY-MM-DD",
                        caption="Reports include up to two years of history. Daily syncs re-read the previous 30 days.",
                    ),
                    SourceFieldInputConfig(
                        name="currency",
                        label="Report currency",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="USD",
                        caption="Enter a supported ISO 4217 currency code, such as USD or EUR.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CriteoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=("CampaignStats",),
            descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()},
            default_incremental_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        )
        for schema in schemas:
            schema.detected_primary_keys = list(ENDPOINTS[schema.name].primary_keys)
        return schemas

    def validate_credentials(
        self, config: CriteoSourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "Unknown Criteo table. Select a supported table."
        try:
            report_start_date(config)
            CriteoClient(config, self.resolve_api_version(api_version)).validate(schema_name)
        except OAuth2AuthRequestError as error:
            if not error.is_permanent:
                raise
            return False, "Criteo rejected the client credentials. Check the client ID and client secret."
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, "Criteo rejected the access token. Check the client credentials."
            if status == 403:
                return False, "Criteo denied access. Check the application permissions and advertiser consent."
            raise
        except ValueError as error:
            return False, str(error)
        return True, None

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Criteo rejected the access token. Update the client credentials and reconnect the source.",
            "403 Client Error": "Criteo denied access. Check the application permissions and advertiser consent.",
            OAUTH2_PERMANENT_ERROR_MARKER: "Criteo rejected the client credentials. Update the client ID and client secret.",
            "Criteo denied access": "Check the application permissions and advertiser consent in Criteo.",
            "daily report row limit": "The daily Criteo report reached its row limit. Contact support to import this report.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CriteoResumeConfig]:
        return ResumableSourceManager(inputs, CriteoResumeConfig)

    def source_for_pipeline(
        self,
        config: CriteoSourceConfig,
        resumable_source_manager: ResumableSourceManager[CriteoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError("Unknown Criteo table. Select a supported table.")
        return criteo_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))
