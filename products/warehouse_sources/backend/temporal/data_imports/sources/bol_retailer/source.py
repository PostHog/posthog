from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bol_retailer.bol_retailer import (
    BolRetailerResumeConfig,
    bol_retailer_source,
    validate_credentials as validate_bol_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bol_retailer.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MERGE_ONLY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bolretailer import (
    BolRetailerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_RECONNECT = "Copy the client ID and secret again from API settings in your bol seller dashboard."


@SourceRegistry.register
class BolRetailerSource(ResumableSource[BolRetailerSourceConfig, BolRetailerResumeConfig]):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True
    # bol versions each resource on its own (v11 for offers, v10 for the rest), so there is no single
    # version to pin.
    api_docs_url = "https://api.bol.com/retailer/public/Retailer-API/v10/releasenotes.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BOLRETAILER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            OAUTH2_PERMANENT_ERROR_MARKER: f"bol rejected the client ID or secret. {_RECONNECT}",
            "401 Client Error: Unauthorized for url: https://api.bol.com": f"bol rejected the access token. {_RECONNECT}",
            "403 Client Error: Forbidden for url: https://api.bol.com": (
                "bol refused access. Check that your seller account is active and has a technical contact in API settings."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bol_retailer.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BolRetailerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY)

    def validate_credentials(
        self,
        config: BolRetailerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bol_credentials(config.client_id, config.client_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BolRetailerResumeConfig]:
        return ResumableSourceManager[BolRetailerResumeConfig](inputs, BolRetailerResumeConfig)

    def source_for_pipeline(
        self,
        config: BolRetailerSourceConfig,
        resumable_source_manager: ResumableSourceManager[BolRetailerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bol_retailer_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BOLRETAILER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            keywords=["bol", "bol.com"],
            label="bol.com Retailer",
            caption="Sync order items, shipments, returns, offers, inventory and invoices from your bol.com seller account.",
            docsUrl="https://posthog.com/docs/cdp/sources/bol-retailer",
            iconPath="/static/services/bol_retailer.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        caption="Create client credentials under Settings > Services > API settings in your bol seller dashboard.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
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
                ],
            ),
        )
