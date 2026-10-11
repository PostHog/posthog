from typing import cast

from sources.checkly._config import ChecklySourceConfig
from sources.checkly.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.checkly.checkly import ChecklyResumeConfig, checkly_source, validate_credentials
from sources.checkly.settings import (
    AUTH_ERRORS,
    DEFAULT_API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SUPPORTED_API_VERSIONS,
)
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class ChecklySource(ResumableSource[ChecklySourceConfig, ChecklyResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = SUPPORTED_API_VERSIONS
    default_version = DEFAULT_API_VERSION
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
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChecklyResumeConfig]:
        return ResumableSourceManager(inputs, ChecklyResumeConfig)

    def source_for_pipeline(
        self,
        config: ChecklySourceConfig,
        resumable_source_manager: ResumableSourceManager[ChecklyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return checkly_source(config, resumable_source_manager, inputs, self.resolve_api_version(inputs.api_version))

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
