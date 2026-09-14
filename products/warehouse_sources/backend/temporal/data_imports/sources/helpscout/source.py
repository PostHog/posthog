from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.helpscout import (
    HelpScoutSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.helpscout import (
    HelpScoutResumeConfig,
    helpscout_source,
    validate_credentials as validate_helpscout_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HelpScoutSource(OAuthMixin, ResumableSource[HelpScoutSourceConfig, HelpScoutResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.helpscout.com/mailbox-api/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HELPSCOUT

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Permanent token-exchange failures (invalid_client, inactive user, …) carry the
            # framework's stable marker; transient 429/5xx token errors don't.
            "401 Client Error: Unauthorized for url: https://api.helpscout.net": "Help Scout authentication failed. Please reconnect your Help Scout account.",
            # The linked OAuth integration was deleted while the source still references it.
            # Retrying can never resolve this, so ask the user to reconnect.
            "Integration not found": "The linked Help Scout integration no longer exists. Please reconnect your Help Scout account.",
            # The Help Scout app isn't configured on this PostHog instance, so the source can't
            # refresh its access token. Deterministic, so retrying never resolves it.
            "Help Scout app not configured": "The Help Scout app is not configured on this PostHog instance. Please contact support.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HELP_SCOUT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            keywords=["helpscout", "helpdesk"],
            label="Help Scout",
            caption="Sync your Help Scout conversations, customers, and mailboxes into the PostHog Data warehouse.",
            iconPath="/static/services/helpscout.png",
            docsUrl="https://posthog.com/docs/cdp/sources/helpscout",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="helpscout_integration_id",
                        label="Help Scout account",
                        required=True,
                        kind="helpscout",
                    ),
                ],
            ),
        )

    def _get_access_token(self, config: HelpScoutSourceConfig, team_id: int) -> str:
        integration = self.get_oauth_integration(config.helpscout_integration_id, team_id)
        # The lookup only scopes to the team, so a config pointing at some other provider's
        # integration in the same team would otherwise send that provider's access token to the
        # Help Scout API. Reject it before the token is read or refreshed.
        if integration.kind != Integration.IntegrationKind.HELPSCOUT:
            raise ValueError(f"Integration not found: {config.helpscout_integration_id}")

        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("Help Scout access token not found")
        return integration.access_token

    def get_schemas(
        self,
        config: HelpScoutSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: HelpScoutSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            return validate_helpscout_credentials(access_token, schema_name)
        except Exception as e:
            return False, str(e)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HelpScoutResumeConfig]:
        return ResumableSourceManager[HelpScoutResumeConfig](inputs, HelpScoutResumeConfig)

    def source_for_pipeline(
        self,
        config: HelpScoutSourceConfig,
        resumable_source_manager: ResumableSourceManager[HelpScoutResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)

        return helpscout_source(
            access_token=access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
