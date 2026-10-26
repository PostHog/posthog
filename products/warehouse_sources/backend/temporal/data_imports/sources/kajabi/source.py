from typing import cast

from requests.exceptions import RequestException

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kajabi import KajabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kajabi.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kajabi.kajabi import (
    KajabiResumeConfig,
    kajabi_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kajabi.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KajabiSource(ResumableSource[KajabiSourceConfig, KajabiResumeConfig]):
    codebase_detection = detect(env=("^KAJABI_",))

    lists_tables_without_credentials = True
    api_docs_url = "https://developers.kajabi.com/api-reference/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAJABI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KAJABI,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Kajabi",
            iconPath="/static/services/kajabi.png",
            docsUrl="https://posthog.com/docs/cdp/sources/kajabi",
            releaseStatus=ReleaseStatus.BETA,
            caption="Create a User API Key in Kajabi's Public API settings. Give it read access to the selected tables.",
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
                        name="site_id",
                        label="Site ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="",
                    ),
                ],
            ),
        )

    def validate_credentials(
        self,
        config: KajabiSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This Kajabi table is not supported. Select another table."
        try:
            status = probe_credentials(config, schema_name)
        except OAuth2AuthRequestError as error:
            if error.is_permanent:
                return False, "Kajabi rejected the client credentials. Check the client ID and client secret."
            return False, "Kajabi could not issue an access token. Try again later."
        except RequestException:
            return False, "Could not connect to Kajabi. Try again later."
        if status == 200 or (status == 403 and schema_name is None):
            return True, None
        if status == 401:
            return False, "Kajabi rejected the access token. Check the client credentials."
        if status == 403:
            return False, "The API key cannot read this table. Give it the required read permission in Kajabi."
        return False, f"Kajabi returned HTTP {status}. Check your site ID and try again."

    def get_schemas(
        self,
        config: KajabiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Kajabi rejected the access token. Check the client credentials and reconnect the source.",
            "403 Client Error": "The Kajabi API key cannot read this table. Update its read permissions and reconnect the source.",
            OAUTH2_PERMANENT_ERROR_MARKER: "Kajabi rejected the client credentials. Check the client ID and client secret, then reconnect the source.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KajabiResumeConfig]:
        return ResumableSourceManager(inputs, KajabiResumeConfig)

    def source_for_pipeline(
        self,
        config: KajabiSourceConfig,
        resumable_source_manager: ResumableSourceManager[KajabiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kajabi_source(config, resumable_source_manager, inputs)
