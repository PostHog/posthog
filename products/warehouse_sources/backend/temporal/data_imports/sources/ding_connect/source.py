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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.ding_connect import (
    DingConnectResumeConfig,
    ding_connect_source,
    validate_credentials as validate_ding_connect_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DingConnectSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DingConnectSource(ResumableSource[DingConnectSourceConfig, DingConnectResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DINGCONNECT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked api_key surfaces as a 401 when `_request` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem. Match the
            # stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.dingconnect.com": "Your DingConnect API key is invalid or has been revoked. Generate a new key under the Developer tab of your DingConnect account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.dingconnect.com": "Your DingConnect API key does not have permission to access this data. Check the key's permissions in your DingConnect account settings, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DingConnectSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "TransferRecords":
                # DingConnect only retains transfer history for ~2 months, so each full-refresh
                # sync reflects the currently-retained window.
                return "Transfer history is only retained upstream for ~2 months. Full refresh only"
            if endpoint == "Balance":
                return "Current account balance per currency. Full refresh only"
            return None

        # No DingConnect endpoint exposes a server-side timestamp filter, so every table is full
        # refresh: the catalog endpoints are static lookups and ListTransferRecords only offers
        # Skip/Take offset paging.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: DingConnectSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_ding_connect_credentials(config.api_key):
            return True, None

        return False, "Invalid DingConnect API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DingConnectResumeConfig]:
        return ResumableSourceManager[DingConnectResumeConfig](inputs, DingConnectResumeConfig)

    def source_for_pipeline(
        self,
        config: DingConnectSourceConfig,
        resumable_source_manager: ResumableSourceManager[DingConnectResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ding_connect_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DING_CONNECT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="DingConnect",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your DingConnect API key to pull your DingConnect data into the PostHog Data warehouse.

You can generate an API key under the **Developer** tab of your [DingConnect account settings](https://www.dingconnect.com/Account/Settings).""",
            iconPath="/static/services/ding_connect.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ding-connect",
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
                ],
            ),
        )
