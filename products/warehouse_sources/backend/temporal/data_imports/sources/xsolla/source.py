from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xsolla import XsollaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.settings import (
    API_DOCS_URL,
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.xsolla import (
    MERCHANT_ID_ERROR,
    XsollaResumeConfig,
    validate_credentials as validate_xsolla_credentials,
    xsolla_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class XsollaSource(ResumableSource[XsollaSourceConfig, XsollaResumeConfig]):
    lists_tables_without_credentials = True
    # The version is the path segment after /merchant. The endpoints this source reads are on v2.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.XSOLLA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR: AUTH_ERROR,
            MERCHANT_ID_ERROR: MERCHANT_ID_ERROR,
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": AUTH_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: XsollaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"transactions"})

    def validate_credentials(
        self,
        config: XsollaSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_xsolla_credentials(config, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[XsollaResumeConfig]:
        return ResumableSourceManager[XsollaResumeConfig](inputs, XsollaResumeConfig)

    def source_for_pipeline(
        self,
        config: XsollaSourceConfig,
        resumable_source_manager: ResumableSourceManager[XsollaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return xsolla_source(
            config=config,
            endpoint_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.XSOLLA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Xsolla",
            caption=(
                "Connect your Xsolla merchant account. Find the merchant ID in "
                "[Publisher Account](https://publisher.xsolla.com/) under **Company settings > Company**. "
                "Create the API key under **Company settings > API keys**. "
                "Use a company API key, because a project API key cannot read merchant reports. "
                "Incremental transaction syncs read the last seven days again to collect status changes."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/xsolla",
            iconPath="/static/services/xsolla.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="merchant_id",
                        label="Merchant ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
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
                ],
            ),
        )
