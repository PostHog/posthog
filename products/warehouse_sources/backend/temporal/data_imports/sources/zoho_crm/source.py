from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zohocrm import (
    ZohoCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOULD_SYNC_DEFAULT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.zoho_crm import (
    REFRESH_TOKEN_REJECTED_MESSAGE,
    ZohoCRMResumeConfig,
    validate_credentials as validate_zoho_crm_credentials,
    zoho_crm_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZohoCRMSource(ResumableSource[ZohoCRMSourceConfig, ZohoCRMResumeConfig]):
    lists_tables_without_credentials = True  # static module catalog — safe for public docs
    supported_versions = ("v8",)
    default_version = "v8"
    api_docs_url = "https://www.zoho.com/crm/developer/docs/api/v8/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOCRM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Zoho CRM token refresh failed": REFRESH_TOKEN_REJECTED_MESSAGE,
            "400 Client Error: Bad Request for url: https://accounts.zoho": "Zoho CRM rejected your OAuth credentials. Check that the client ID, client secret, and refresh token all belong to the same self client.",
            "401 Client Error: Unauthorized for url": "Your Zoho CRM access token is invalid or expired. Reconnect the source to issue a new one.",
            "403 Client Error: Forbidden for url": "Your Zoho CRM token is missing a scope for this module. Re-authorize with the ZohoCRM.modules.ALL and ZohoCRM.settings.fields.READ scopes.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZOHO_CRM,
            category=DataWarehouseSourceCategory.CRM,
            keywords=["zoho"],
            label="Zoho CRM",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your Zoho CRM account to pull leads, contacts, deals, and your other modules into the PostHog Data warehouse.

In the [Zoho API console](https://api-console.zoho.com), create a **Self Client** and generate a refresh token for the scopes `ZohoCRM.modules.ALL` and `ZohoCRM.settings.fields.READ`. Paste the client ID, client secret, and refresh token below, then pick the data center your Zoho account lives in.""",
            iconPath="/static/services/zoho_crm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zoho-crm",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Data center",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="United States (.com)", value="us"),
                            SourceFieldSelectConfigOption(label="Europe (.eu)", value="eu"),
                            SourceFieldSelectConfigOption(label="India (.in)", value="in"),
                            SourceFieldSelectConfigOption(label="Australia (.com.au)", value="au"),
                            SourceFieldSelectConfigOption(label="Japan (.jp)", value="jp"),
                            SourceFieldSelectConfigOption(label="Canada (.ca)", value="ca"),
                            SourceFieldSelectConfigOption(label="China (.com.cn)", value="cn"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1000.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="1000.XXXXXXXX.XXXXXXXX",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ZohoCRMSourceConfig,
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
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )

    def validate_credentials(
        self,
        config: ZohoCRMSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, error = validate_zoho_crm_credentials(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            api_version=self.resolve_api_version(api_version),
        )
        if is_valid:
            return True, None

        return False, error or "Invalid Zoho CRM credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZohoCRMResumeConfig]:
        # Each module keeps its own cursor: page tokens are bound to the query that issued them.
        return ResumableSourceManager[ZohoCRMResumeConfig](inputs, ZohoCRMResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: ZohoCRMSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZohoCRMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zoho_crm_source(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
