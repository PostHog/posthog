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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZendeskSellSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.zendesk_sell import (
    ZendeskSellResumeConfig,
    validate_credentials as validate_zendesk_sell_credentials,
    zendesk_sell_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZendeskSellSource(ResumableSource[ZendeskSellSourceConfig, ZendeskSellResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENDESKSELL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZENDESK_SELL,
            category=DataWarehouseSourceCategory.CRM,
            label="Zendesk Sell",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Zendesk Sell access token to pull your Sell (formerly Base CRM) data into the PostHog Data warehouse.

Create a personal access token under **Settings > Integrations > OAuth > Access Tokens** in Zendesk Sell. A read-only token is sufficient.""",
            iconPath="/static/services/zendesk_sell.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zendesk-sell",
            # Alpha: ships hidden until the end-to-end sync is verified against a live account.
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing/expired/invalid token surfaces as a requests HTTPError once `raise_for_status`
            # runs. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.getbase.com": "Your Zendesk Sell access token is invalid or has expired. Create a new access token in your Zendesk Sell settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.getbase.com": "Your Zendesk Sell access token is missing the permissions needed to sync this data. Grant read access and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ZendeskSellSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # All endpoints are full refresh: the Core API has no server-side timestamp filter, so there's
        # no cheap incremental sync. See zendesk_sell.py for details.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ZendeskSellSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_zendesk_sell_credentials(config.access_token):
            return True, None

        return False, "Invalid Zendesk Sell access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZendeskSellResumeConfig]:
        return ResumableSourceManager[ZendeskSellResumeConfig](inputs, ZendeskSellResumeConfig)

    def source_for_pipeline(
        self,
        config: ZendeskSellSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZendeskSellResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zendesk_sell_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
