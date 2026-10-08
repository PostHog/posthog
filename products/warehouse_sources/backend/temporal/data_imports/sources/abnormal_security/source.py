from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.abnormal_security import (
    AUTH_ERRORS,
    AbnormalSecurityResumeConfig,
    abnormal_security_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.settings import (
    API_DOCS_URL,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.abnormalsecurity import (
    AbnormalSecuritySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AbnormalSecuritySource(ResumableSource[AbnormalSecuritySourceConfig, AbnormalSecurityResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ABNORMALSECURITY

    @property
    def connection_host_fields(self) -> list[str]:
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ABNORMALSECURITY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Abnormal Security (Abnormal AI)",
            iconPath="/static/services/abnormal_security.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Create an API token in [Abnormal Settings > Integrations > Abnormal REST API]"
                "(https://portal.abnormalsecurity.com/home/settings/integrations). "
                "Select your account region. Allow PostHog's outbound IP addresses if your account restricts API access. "
                "Cases require an Account Takeover license. "
                "Threat rows contain campaign details and the API's limited message sample."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US", value="us"),
                            SourceFieldSelectConfigOption(label="EU", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(AUTH_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AbnormalSecuritySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=("cases", "vendor_cases"),
            should_sync_default={"cases": False, "vendor_cases": False},
        )

    def validate_credentials(
        self,
        config: AbnormalSecuritySourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, api_version)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AbnormalSecurityResumeConfig]:
        return ResumableSourceManager(inputs, AbnormalSecurityResumeConfig)

    def source_for_pipeline(
        self,
        config: AbnormalSecuritySourceConfig,
        resumable_source_manager: ResumableSourceManager[AbnormalSecurityResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return abnormal_security_source(config, resumable_source_manager, inputs)
