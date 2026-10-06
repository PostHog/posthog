from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.checkly import (
    ChecklyResumeConfig,
    checkly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.settings import (
    API_VERSION,
    AUTH_ERRORS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkly import (
    ChecklySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChecklySource(ResumableSource[ChecklySourceConfig, ChecklyResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://api.checklyhq.com/openapi.json"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHECKLY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{status} Client Error": message for status, message in AUTH_ERRORS.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ChecklySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ChecklySourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, api_version or API_VERSION)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChecklyResumeConfig]:
        return ResumableSourceManager(inputs, ChecklyResumeConfig)

    def source_for_pipeline(
        self,
        config: ChecklySourceConfig,
        resumable_source_manager: ResumableSourceManager[ChecklyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return checkly_source(config, resumable_source_manager, inputs)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHECKLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Checkly",
            caption="Create an API key in [Checkly user settings](https://app.checklyhq.com/settings/user/api-keys). "
            "Copy your account ID from [account settings](https://app.checklyhq.com/settings/account/general). "
            "Check results include up to 30 days of available history.",
            iconPath="/static/services/checkly.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                ],
            ),
        )
