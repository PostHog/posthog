from typing import cast

from requests.exceptions import HTTPError, RequestException

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kisi import KisiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.kisi import (
    KisiResumeConfig,
    kisi_source,
    validate_credentials as validate_kisi_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    OFFSET_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KisiSource(ResumableSource[KisiSourceConfig, KisiResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.kisi.io/platform/apis/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KISI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KISI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kisi",
            iconPath="/static/services/kisi.png",
            caption="In Kisi, open My Account > API > Add API Key. Use an organization owner or administrator account.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "Wrong email address or password": AUTH_ERROR,
            OFFSET_ERROR: OFFSET_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KisiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: KisiSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            validate_kisi_credentials(config.api_key)
        except HTTPError as error:
            if error.response is not None:
                if error.response.status_code == 401:
                    return False, AUTH_ERROR
                if error.response.status_code == 403:
                    return False, PERMISSION_ERROR
            return False, "Kisi could not validate the API key. Try again later."
        except RequestException:
            return False, "Could not connect to Kisi. Try again later."
        except ValueError:
            return False, "Kisi returned an unexpected response. Try again later."
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KisiResumeConfig]:
        return ResumableSourceManager(inputs, KisiResumeConfig)

    def source_for_pipeline(
        self,
        config: KisiSourceConfig,
        resumable_source_manager: ResumableSourceManager[KisiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kisi_source(config.api_key, inputs, resumable_source_manager)
