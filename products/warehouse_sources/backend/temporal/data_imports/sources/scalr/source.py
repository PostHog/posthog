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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scalr import ScalrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scalr.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scalr.scalr import (
    ScalrResumeConfig,
    scalr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scalr.settings import (
    ACCESS_ERROR,
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ScalrSource(ResumableSource[ScalrSourceConfig, ScalrResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.scalr.io/reference/overview-1"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCALR

    @property
    def connection_host_fields(self) -> list[str]:
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ScalrSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"workspaces"})

    def validate_credentials(
        self,
        config: ScalrSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            validate_credentials(config, team_id, self.resolve_api_version(api_version))
        except ValueError as error:
            return False, str(error)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, AUTH_ERROR
            if status in (403, 404):
                return False, ACCESS_ERROR
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ScalrResumeConfig]:
        return ResumableSourceManager(inputs, ScalrResumeConfig)

    def source_for_pipeline(
        self,
        config: ScalrSourceConfig,
        resumable_source_manager: ResumableSourceManager[ScalrResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return scalr_source(config, resumable_source_manager, inputs, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SCALR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Scalr",
            caption="Create a service account token in Scalr under account scope > IAM > Service accounts. "
            "Give the account read access to environments, workspaces, and runs.",
            iconPath="/static/services/scalr.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Scalr hostname",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.scalr.io",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acc-example",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
