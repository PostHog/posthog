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
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.cisco_meraki import (
    CiscoMerakiResumeConfig,
    cisco_meraki_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_meraki.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    NOT_FOUND_ERROR,
    ORGANIZATION_ERROR,
    PERMISSION_ERROR,
    REGION_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ciscomeraki import (
    CiscoMerakiSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CiscoMerakiSource(ResumableSource[CiscoMerakiSourceConfig, CiscoMerakiResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.cisco.com/meraki/api-v1/versioning/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CISCOMERAKI

    @property
    def connection_host_fields(self) -> list[str]:
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            "404 Client Error": NOT_FOUND_ERROR,
            REGION_ERROR: REGION_ERROR,
            ORGANIZATION_ERROR: ORGANIZATION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CiscoMerakiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: CiscoMerakiSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CiscoMerakiResumeConfig]:
        return ResumableSourceManager(inputs, CiscoMerakiResumeConfig)

    def source_for_pipeline(
        self,
        config: CiscoMerakiSourceConfig,
        resumable_source_manager: ResumableSourceManager[CiscoMerakiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cisco_meraki_source(
            config,
            inputs.schema_name,
            self.resolve_api_version(inputs.api_version),
            inputs.team_id,
            inputs.job_id,
            resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CISCOMERAKI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cisco Meraki",
            iconPath="/static/services/cisco_meraki.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "In Meraki Dashboard, open **Organization > API & Webhooks > API keys and access**. Create an API key. "
                "Enable API access for your organization. Use an administrator account with read access to the selected tables. "
                "Each connection imports one organization. Tables use full refresh. Health alerts include active alerts only."
            ),
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
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="global",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Global (Americas, Europe, Asia-Pacific)", value="global"
                            ),
                            SourceFieldSelectConfigOption(label="Canada", value="canada"),
                            SourceFieldSelectConfigOption(label="China", value="china"),
                            SourceFieldSelectConfigOption(label="India", value="india"),
                            SourceFieldSelectConfigOption(label="US Government", value="us_government"),
                        ],
                    ),
                ],
            ),
        )
