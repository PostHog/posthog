from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.chargedesk import (
    ChargedeskResumeConfig,
    chargedesk_source,
    validate_credentials as validate_chargedesk_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.settings import (
    CHARGEDESK_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChargedeskSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChargedeskSource(ResumableSource[ChargedeskSourceConfig, ChargedeskResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARGEDESK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHARGEDESK,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Chargedesk",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your ChargeDesk secret API key to automatically pull your ChargeDesk data into the PostHog Data warehouse.

Each company has its own secret key. Create one in your ChargeDesk account under **Setup → API / Webhooks → Issue New Key**, and make sure API access is enabled for the company.""",
            iconPath="/static/services/chargedesk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/chargedesk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad or disabled secret key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so stop the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.chargedesk.com": "Your ChargeDesk secret API key is invalid or has been revoked. Issue a new key in your ChargeDesk account (Setup → API / Webhooks) and reconnect.",
            "403 Client Error: Forbidden for url: https://api.chargedesk.com": "Your ChargeDesk secret API key does not have API access enabled. Enable API access for the company in your ChargeDesk account and reconnect.",
        }

    def get_schemas(
        self,
        config: ChargedeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            cfg = CHARGEDESK_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=cfg.supports_incremental,
                supports_append=cfg.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ChargedeskSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_chargedesk_credentials(config.api_key):
            return True, None

        return False, "Invalid ChargeDesk secret API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChargedeskResumeConfig]:
        return ResumableSourceManager[ChargedeskResumeConfig](inputs, ChargedeskResumeConfig)

    def source_for_pipeline(
        self,
        config: ChargedeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[ChargedeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return chargedesk_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value
            if inputs.should_use_incremental_field
            else None,
        )
