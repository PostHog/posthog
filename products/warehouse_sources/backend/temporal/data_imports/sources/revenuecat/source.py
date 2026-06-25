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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    ResumableSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RevenueCatSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat import revenuecat as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    EVENT_RESOURCE_NAME,
    RESOURCE_TO_REVENUECAT_EVENT_TYPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat import (
    RevenueCatResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.settings import (
    REVENUECAT_API_ENDPOINTS,
    REVENUECAT_API_SCHEMA_NAMES,
    REVENUECAT_WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


REVENUECAT_API_KEYS_URL = "https://app.revenuecat.com/projects/_/api-keys"


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Unwrap RevenueCat's ``{"event": {...}, "api_version": "1.0"}`` envelope.

    Webhook deliveries land in S3 as raw POST bodies. RevenueCat nests the
    interesting payload under ``event`` — we hoist it so the warehouse table
    columns match the documented event field names directly. ``api_version`` is
    kept as a sibling column so consumers can detect upstream schema changes.

    We also derive a ``created_at`` field (Unix seconds) from RevenueCat's
    ``event_timestamp_ms`` so this table can share the same datetime partition
    convention as the API endpoints. The original ``event_timestamp_ms`` is
    preserved unchanged for callers that need sub-second precision.
    """
    if "event" not in table.column_names:
        return table_from_py_list([])

    event_col = table.column("event").to_pylist()
    api_version_col = (
        table.column("api_version").to_pylist() if "api_version" in table.column_names else [None] * table.num_rows
    )

    rows: list[dict[str, Any]] = []
    for event, api_version in zip(event_col, api_version_col):
        if event is None:
            continue
        # Defensive: `event` typically arrives as a nested dict (pyarrow struct),
        # but we accept a JSON-serialized string too in case the upstream
        # buffering layer flattens nested structures.
        row = orjson.loads(event) if isinstance(event, (str, bytes)) else dict(event)
        row["api_version"] = api_version
        event_ts_ms = row.get("event_timestamp_ms")
        if isinstance(event_ts_ms, int) and not isinstance(event_ts_ms, bool):
            row["created_at"] = event_ts_ms // 1000
        rows.append(row)

    return table_from_py_list(rows)


@SourceRegistry.register
class RevenueCatSource(
    ResumableSource[RevenueCatSourceConfig, RevenueCatResumeConfig],
    WebhookSource[RevenueCatSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REVENUECAT

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.webhook_template import (
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_REVENUECAT_EVENT_TYPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REVENUE_CAT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="RevenueCat",
            caption=(
                "Connect your RevenueCat project using a "
                f"[v2 secret API key]({REVENUECAT_API_KEYS_URL}). PostHog uses the key to pull "
                "customers, products, entitlements, offerings, and apps, and to register a webhook "
                "integration for realtime subscription and purchase events."
            ),
            iconPath="/static/services/revenuecat.png",
            docsUrl="https://posthog.com/docs/cdp/sources/revenuecat",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        caption=(
                            f"Generate a [v2 secret API key]({REVENUECAT_API_KEYS_URL}) "
                            "with read access to customers, products, entitlements, offerings, "
                            "apps, and integrations (read/write for automatic webhook setup)."
                        ),
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="proj1a2b3c4d5e",
                        caption=(
                            "The id that starts with `proj`, found in your RevenueCat dashboard URL: "
                            "`app.revenuecat.com/projects/<project_id>`. You can paste either the id "
                            "or the full URL."
                        ),
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.BETA,
            featureFlag="dwh-revenuecat",
            webhookSetupCaption=(
                "PostHog tries to register a webhook integration in RevenueCat using your "
                "secret API key. RevenueCat does not HMAC-sign deliveries — instead, the "
                "integration sends a custom **Authorization** header on every request, whose "
                "value you set below. PostHog rejects deliveries whose header does not match.\n\n"
                "**Manual setup** (only needed if auto-registration failed):\n\n"
                "1. Go to your **RevenueCat project** > **Integrations** > **+ New** > **Webhook**\n"
                "2. Paste the webhook URL shown below into the **Webhook URL** field\n"
                "3. Set the **Authorization header** to a secret value you generate locally — "
                "paste the same value into the field below so PostHog can verify deliveries\n"
                "4. Select **All events** under **Send events**\n"
                "5. Click **Save**"
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="authorization_header",
                        label="Authorization header value",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Bearer my-secret",
                        caption=(
                            "The exact value RevenueCat will send in the Authorization header. "
                            "Must match what's configured in the RevenueCat webhook integration."
                        ),
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "RevenueCat rejected the API key. Generate a new v2 secret API key and reconnect."
            ),
            "403 Client Error: Forbidden": (
                "The API key doesn't have permission for this endpoint. Check that the key has "
                "read access to the resources you're syncing."
            ),
            "404 Client Error: Not Found": (
                "RevenueCat could not find the project. Double-check the project id and that the API key belongs to it."
            ),
        }

    def validate_credentials(
        self, config: RevenueCatSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return api_client.validate_credentials(config.secret_api_key, config.project_id)

    def get_schemas(
        self,
        config: RevenueCatSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # `events` is webhook-only — the v2 API doesn't expose a historical
        # backfill endpoint for webhook events, so the only way to populate
        # this table is via realtime webhook deliveries.
        webhook_schemas = [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=True,
                incremental_fields=[],
            )
            for name in REVENUECAT_WEBHOOK_SCHEMA_NAMES
        ]
        # API endpoints don't expose a server-side `created_at >= X` filter, so
        # "incremental" syncs would still scan every page. Default to full
        # refresh and let the partitioning column (`created_at`) keep delta
        # writes cheap.
        api_schemas = [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=False,
                incremental_fields=[],
            )
            for name in REVENUECAT_API_SCHEMA_NAMES
        ]
        schemas = [*webhook_schemas, *api_schemas]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RevenueCatResumeConfig]:
        return ResumableSourceManager[RevenueCatResumeConfig](inputs, RevenueCatResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: RevenueCatSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        # RevenueCat requires the auth-header value at integration creation
        # time, but the user hasn't entered it yet on the warehouse side. Skip
        # passing one and the surrounding flow will collect it via
        # `webhookFields`, then re-create the integration to bind it.
        return api_client.create_webhook(
            api_key=config.secret_api_key,
            project_id=config.project_id,
            webhook_url=webhook_url,
        )

    def webhook_inputs_updated(
        self, config: RevenueCatSourceConfig, webhook_url: str, team_id: int, inputs: dict[str, Any]
    ) -> tuple[bool, str | None]:
        # Once the user provides the authorization header value, re-register
        # the integration so RevenueCat starts sending the header on every
        # delivery. RevenueCat's API doesn't let you update the auth header on
        # an existing integration in-place — delete + recreate is the
        # supported path.
        header_value = inputs.get("authorization_header")
        if not header_value:
            return True, None

        deletion = api_client.delete_webhook(config.secret_api_key, config.project_id, webhook_url)
        if not deletion.success:
            return False, deletion.error or "Failed to refresh RevenueCat webhook integration."

        creation = api_client.create_webhook(
            api_key=config.secret_api_key,
            project_id=config.project_id,
            webhook_url=webhook_url,
            authorization_header_value=header_value,
        )
        if not creation.success:
            return False, creation.error or "Failed to bind the new authorization header."
        return True, None

    def get_external_webhook_info(
        self, config: RevenueCatSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(config.secret_api_key, config.project_id, webhook_url)

    def delete_webhook(self, config: RevenueCatSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        return api_client.delete_webhook(config.secret_api_key, config.project_id, webhook_url)

    def source_for_pipeline(
        self,
        config: RevenueCatSourceConfig,
        resumable_source_manager: ResumableSourceManager[RevenueCatResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name == EVENT_RESOURCE_NAME:
            return self._webhook_source_response(inputs)
        return self._api_source_response(config, resumable_source_manager, inputs)

    def _webhook_source_response(self, inputs: SourceInputs) -> SourceResponse:
        webhook_source_manager = self.get_webhook_source_manager(inputs)
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(True)

        def items() -> Iterable[Any] | AsyncIterable[Any]:
            if webhook_enabled:
                return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
            return iter([])

        return SourceResponse(
            items=items,
            primary_keys=["id"],
            name=inputs.schema_name,
            sort_mode="asc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            # `created_at` is derived in the webhook transformer from
            # `event_timestamp_ms / 1000` so it lands here as Unix seconds —
            # the partition layer treats bare ints as seconds, so this gives
            # us correctly-bucketed weekly partitions.
            partition_keys=["created_at"],
        )

    def _api_source_response(
        self,
        config: RevenueCatSourceConfig,
        resumable_source_manager: ResumableSourceManager[RevenueCatResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = REVENUECAT_API_ENDPOINTS[inputs.schema_name]

        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        starting_after = resume.starting_after if resume is not None and resume.endpoint == inputs.schema_name else None

        def on_cursor_advance(endpoint_name: str, last_id: str) -> None:
            resumable_source_manager.save_state(RevenueCatResumeConfig(endpoint=endpoint_name, starting_after=last_id))

        def items() -> Iterable[dict[str, Any]]:
            yield from api_client.iterate_list_endpoint(
                api_key=config.secret_api_key,
                project_id=config.project_id,
                path_suffix=endpoint.path_suffix,
                endpoint_name=inputs.schema_name,
                timestamp_fields=tuple(endpoint.partition_keys),
                starting_after=starting_after,
                on_cursor_advance=on_cursor_advance,
            )

        # Datetime partitioning on the endpoint's timestamp field (`created_at`,
        # or `first_seen_at` for customers) — `iterate_list_endpoint` normalizes
        # RevenueCat's ms-epoch value down to Unix seconds so the partition layer
        # (which treats bare ints as seconds) produces sane bucket dates.
        return SourceResponse(
            items=items,
            primary_keys=endpoint.primary_keys,
            name=inputs.schema_name,
            partition_keys=endpoint.partition_keys,
            partition_mode="datetime",
            partition_format="week",
            partition_count=1,
            partition_size=1,
        )
