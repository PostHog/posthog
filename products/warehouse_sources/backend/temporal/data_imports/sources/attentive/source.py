import hashlib
from collections.abc import AsyncIterable, Iterable
from typing import TYPE_CHECKING, Any, Optional, cast

import orjson
import pyarrow as pa
from asgiref.sync import async_to_sync

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
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.attentive import api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.attentive.constants import (
    ATTENTIVE_WEBHOOK_SCHEMA_NAMES,
    RESOURCE_TO_ATTENTIVE_EVENT_TYPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    SimpleSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AttentiveSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Add a synthetic ``event_id`` and a ``created_at`` partition column.

    Attentive webhook payloads carry no top-level event id, so we derive a
    stable hash of the full payload — identical retried deliveries dedupe to
    the same row. ``created_at`` (Unix seconds) is derived from Attentive's
    millisecond ``timestamp`` for datetime partitioning.
    """
    rows: list[dict[str, Any]] = []
    for row in table.to_pylist():
        row = dict(row)
        # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
        row["event_id"] = hashlib.md5(orjson.dumps(row, option=orjson.OPT_SORT_KEYS, default=str)).hexdigest()
        timestamp_ms = row.get("timestamp")
        if isinstance(timestamp_ms, int) and not isinstance(timestamp_ms, bool):
            row["created_at"] = timestamp_ms // 1000
        rows.append(row)

    return table_from_py_list(rows)


@SourceRegistry.register
class AttentiveSource(
    SimpleSource[AttentiveSourceConfig],
    WebhookSource[AttentiveSourceConfig],
):
    api_docs_url = "https://docs.attentive.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ATTENTIVE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.attentive.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_ATTENTIVE_EVENT_TYPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ATTENTIVE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Attentive",
            caption=(
                "Connect your Attentive account using a private app API key (Marketplace > Create app). "
                "Attentive's API has no bulk read endpoints, so all tables are populated from webhook "
                "events as they happen — history before the connection date is not backfilled."
            ),
            iconPath="/static/services/attentive.com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/attentive",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Attentive private app API key",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption=(
                "PostHog tries to register the webhook for you using your API key. Attentive doesn't "
                "return the signing key in the API response, so you still need to copy it from the "
                "webhook's settings in Attentive and paste it below."
                "\n\n**Manual setup** (only needed if auto-registration failed):\n\n"
                "1. In Attentive, go to **Marketplace** > your private app > **Webhooks**\n"
                "2. Paste the webhook URL shown below into the **Destination URL** field\n"
                "3. Select the events you want to track (SMS, email, custom attributes)\n"
                "4. Save the webhook\n\n"
                "Then copy the webhook's **signing key** into the field below."
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Attentive webhook signing key",
                        secret=True,
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: AttentiveSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return api_client.validate_credentials(config.api_key)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.attentive.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Attentive rejected the API key. Create a private app under Marketplace > Create app "
                "in Attentive and reconnect with its API key."
            ),
            "403 Client Error: Forbidden": (
                "The API key doesn't have permission for this endpoint. Make sure the private app has "
                "the Webhooks permission."
            ),
        }

    def get_schemas(
        self,
        config: AttentiveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # All tables are webhook-only: Attentive's REST API has no list
        # endpoints to poll, so user-facing append/full-refresh toggles don't
        # apply and there is nothing for the polling sync to fetch.
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=True,
                incremental_fields=[],
            )
            for name in ATTENTIVE_WEBHOOK_SCHEMA_NAMES
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: AttentiveSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        return api_client.create_webhook(
            api_key=config.api_key,
            webhook_url=webhook_url,
            resource_names=list(RESOURCE_TO_ATTENTIVE_EVENT_TYPE.keys()),
        )

    def webhook_inputs_updated(
        self, config: AttentiveSourceConfig, webhook_url: str, team_id: int, inputs: dict[str, Any]
    ) -> tuple[bool, str | None]:
        # The webhook is disabled right after creation so Attentive doesn't
        # fire events at PostHog before we can verify them with the signing
        # key. Now that the user has provided the key, enable the webhook.
        if not inputs.get("signing_secret"):
            return True, None
        return api_client.enable_webhook(config.api_key, webhook_url)

    def get_desired_webhook_events(
        self, config: AttentiveSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return [
            RESOURCE_TO_ATTENTIVE_EVENT_TYPE[name]
            for name in eligible_schema_names
            if name in RESOURCE_TO_ATTENTIVE_EVENT_TYPE
        ]

    def sync_webhook_events(
        self,
        config: AttentiveSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        return api_client.sync_webhook_events(config.api_key, webhook_url, eligible_schema_names)

    def get_external_webhook_info(
        self, config: AttentiveSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(config.api_key, webhook_url)

    def delete_webhook(self, config: AttentiveSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        return api_client.delete_webhook(config.api_key, webhook_url)

    def source_for_pipeline(self, config: AttentiveSourceConfig, inputs: SourceInputs) -> SourceResponse:
        webhook_source_manager = self.get_webhook_source_manager(inputs)
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(True)

        def items() -> Iterable[Any] | AsyncIterable[Any]:
            if webhook_enabled:
                return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
            return iter([])

        return SourceResponse(
            items=items,
            primary_keys=["event_id"],
            name=inputs.schema_name,
            sort_mode="asc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=["created_at"],
        )
