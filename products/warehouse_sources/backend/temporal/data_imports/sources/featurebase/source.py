from typing import TYPE_CHECKING, Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    ResumableSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.featurebase import (
    FeaturebaseResumeConfig,
    all_desired_webhook_topics,
    create_webhook as create_featurebase_webhook,
    delete_webhook as delete_featurebase_webhook,
    featurebase_source,
    get_external_webhook_info as get_featurebase_webhook_info,
    sync_webhook_events as sync_featurebase_webhook_events,
    validate_credentials as validate_featurebase_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.settings import (
    ENDPOINTS,
    FEATUREBASE_ENDPOINTS,
    INCREMENTAL_FIELDS,
    RESOURCE_TO_FEATUREBASE_OBJECT_TYPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FeaturebaseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class FeaturebaseSource(
    ResumableSource[FeaturebaseSourceConfig, FeaturebaseResumeConfig],
    WebhookSource[FeaturebaseSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FEATUREBASE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FEATUREBASE,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Featurebase",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Enter your Featurebase API key to pull your feedback posts, boards, comments, "
                "upvoters, changelogs, and users into the PostHog Data warehouse.\n\n"
                "You can create an API key in your Featurebase dashboard under "
                "**Settings** > **API**."
            ),
            iconPath="/static/services/featurebase.png",
            docsUrl="https://posthog.com/docs/cdp/sources/featurebase",
            keywords=["feedback", "roadmap", "changelog"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Featurebase API key",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption=(
                "PostHog registers the Featurebase webhook for you using your API key, including "
                "the signing secret — no manual steps needed.\n\n"
                "**Manual setup** (only needed if auto-registration failed, e.g. your organization "
                "hit Featurebase's webhook limit):\n\n"
                "1. In Featurebase, go to **Settings** > **Webhooks** > **Add webhook**\n"
                "2. Paste the webhook URL shown below into the **URL** field\n"
                "3. Subscribe to the post, comment, and changelog topics\n"
                "4. Copy the **Signing secret** into the field below"
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="whsec_...",
                        secret=True,
                    ),
                ],
            ),
        )

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.webhook_template import (
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_FEATUREBASE_OBJECT_TYPE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Featurebase responds 403 for missing/invalid API keys (verified against the live
        # API); 401 is matched too in case that ever changes. Retrying can never satisfy a
        # credential problem, so stop the sync.
        return {
            "401 Client Error: Unauthorized for url: https://do.featurebase.app": (
                "Your Featurebase API key is invalid or has been revoked. Create a new API key in "
                "your Featurebase dashboard under Settings > API, then reconnect."
            ),
            "403 Client Error: Forbidden for url: https://do.featurebase.app": (
                "Featurebase rejected your API key. Create a new API key in your Featurebase "
                "dashboard under Settings > API, then reconnect."
            ),
        }

    def get_schemas(
        self,
        config: FeaturebaseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "post_voters":
                return (
                    "Maps which users upvoted which post as one row per (post, voter). "
                    "Costs one request chain per post, so it's off by default"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FEATUREBASE_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # All resources are mutable (posts/comments get edited, changelogs republished),
                # so merge is the only safe write disposition — append would duplicate rows.
                supports_append=False,
                supports_webhooks=endpoint in RESOURCE_TO_FEATUREBASE_OBJECT_TYPE,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FeaturebaseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        valid, error = validate_featurebase_credentials(config.api_key)
        if valid:
            return True, None
        return False, error or "Invalid Featurebase API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FeaturebaseResumeConfig]:
        return ResumableSourceManager[FeaturebaseResumeConfig](inputs, FeaturebaseResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: FeaturebaseSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        return create_featurebase_webhook(config.api_key, webhook_url)

    def get_desired_webhook_events(
        self, config: FeaturebaseSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Every mappable topic, not just the selected tables — auto-heals webhooks created
        # before a table was enabled; unmapped events are dropped by the hog function.
        return all_desired_webhook_topics()

    def sync_webhook_events(
        self,
        config: FeaturebaseSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        desired_topics = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return sync_featurebase_webhook_events(config.api_key, webhook_url, desired_topics)

    def get_external_webhook_info(
        self, config: FeaturebaseSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo | None:
        return get_featurebase_webhook_info(config.api_key, webhook_url)

    def delete_webhook(self, config: FeaturebaseSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        return delete_featurebase_webhook(config.api_key, webhook_url)

    def source_for_pipeline(
        self,
        config: FeaturebaseSourceConfig,
        resumable_source_manager: ResumableSourceManager[FeaturebaseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return featurebase_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
