import re
from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.daisycon import (
    DaisyconPublisherError,
    DaisyconResumeConfig,
    daisycon_source,
    probe_token,
    resolve_publisher_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.oauth import (
    DAISYCON_GRANT_REVOKED_ERROR,
    DaisyconIntegrationAuth,
    resolve_daisycon_oauth_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.settings import (
    DEFAULT_CURRENCY,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LOOKBACK_SECONDS,
    MERGE_ONLY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.daisycon import (
    DaisyconSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_RECONNECT = "Reconnect your Daisycon account in the source settings."
_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


@SourceRegistry.register
class DaisyconSource(ResumableSource[DaisyconSourceConfig, DaisyconResumeConfig], OAuthMixin):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True
    api_docs_url = "https://docs-publisher.daisycon.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DAISYCON

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://services.daisycon.com": (
                f"Daisycon rejected the connection. The authorization lapses after 30 days without a sync. {_RECONNECT}"
            ),
            "403 Client Error: Forbidden for url: https://services.daisycon.com": (
                "The connected Daisycon login cannot read this data. Check its publisher permissions in Daisycon."
            ),
            "Missing integration ID": f"The Daisycon connection is missing. {_RECONNECT}",
            "Integration not found": f"The linked Daisycon connection no longer exists. {_RECONNECT}",
            "Daisycon access token not found": f"The Daisycon access token is missing. {_RECONNECT}",
            DAISYCON_GRANT_REVOKED_ERROR: f"Daisycon no longer accepts the authorization. {_RECONNECT}",
            "The connected Daisycon login cannot read publisher": None,
            "The connected Daisycon login can read more than one publisher": None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DaisyconSourceConfig,
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
            merge_only=MERGE_ONLY,
            default_incremental_lookback_seconds=LOOKBACK_SECONDS,
        )

    def validate_credentials(
        self,
        config: DaisyconSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.daisycon_integration_id:
            return False, "Connect your Daisycon account."
        try:
            currency_code = (config.currency_code or DEFAULT_CURRENCY).strip().upper()
            if not _CURRENCY_CODE.fullmatch(currency_code):
                return False, "Enter a three-letter currency code, such as EUR."
            integration = self.get_oauth_integration(config.daisycon_integration_id, team_id)
            # The sync checks the publisher against the list stored at connect time, so setup does too.
            resolve_publisher_id(config.publisher_id, list(integration.config.get("daisycon_publisher_ids") or []))
            token = resolve_daisycon_oauth_token(config.daisycon_integration_id, team_id)
            status = probe_token(token)
            if status == 401:
                return False, f"Daisycon rejected the connection. {_RECONNECT}"
            if status != 200:
                return False, "Could not reach Daisycon. Try again in a minute."
        except (ValueError, DaisyconPublisherError) as e:
            return False, str(e)
        except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
            return False, "Could not reach Daisycon. Try again in a minute."
        return True, None

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                f"The linked Daisycon connection no longer exists. {_RECONNECT}"
            ) from e
        return [
            IntegrationAccount(value=publisher["id"], display_name=publisher["name"], secondary_text=publisher["id"])
            for publisher in integration.config.get("daisycon_publishers") or []
        ]

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DaisyconResumeConfig]:
        return ResumableSourceManager[DaisyconResumeConfig](inputs, DaisyconResumeConfig)

    def source_for_pipeline(
        self,
        config: DaisyconSourceConfig,
        resumable_source_manager: ResumableSourceManager[DaisyconResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if not config.daisycon_integration_id:
            raise ValueError("Missing integration ID")
        integration = self.get_oauth_integration(config.daisycon_integration_id, inputs.team_id)
        publisher_id = resolve_publisher_id(
            config.publisher_id, list(integration.config.get("daisycon_publisher_ids") or [])
        )
        token = resolve_daisycon_oauth_token(config.daisycon_integration_id, inputs.team_id)
        return daisycon_source(
            auth=DaisyconIntegrationAuth(config.daisycon_integration_id, inputs.team_id, token),
            publisher_id=publisher_id,
            endpoint=inputs.schema_name,
            currency_code=(config.currency_code or DEFAULT_CURRENCY).strip().upper(),
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
            name=ExternalDataSourceType.DAISYCON,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["affiliate"],
            label="Daisycon",
            caption="Sync transactions, daily statistics, programs and media from your Daisycon publisher account.",
            docsUrl="https://posthog.com/docs/cdp/sources/daisycon",
            iconPath="/static/services/daisycon.png",
            releaseStatus=ReleaseStatus.ALPHA,
            # Connecting needs the PostHog Daisycon OAuth app, so the flag stays off until its secret is deployed.
            featureFlag="dwh-daisycon",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="daisycon_integration_id",
                        label="Daisycon account",
                        required=True,
                        kind="daisycon",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="publisher_id",
                        label="Publisher",
                        integrationField="daisycon_integration_id",
                        integrationKind="daisycon",
                        required=True,
                        placeholder="Pick the publisher to sync",
                    ),
                    SourceFieldInputConfig(
                        name="currency_code",
                        label="Statistics currency",
                        caption="Three-letter currency code for the daily statistics table.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DEFAULT_CURRENCY,
                        secret=False,
                    ),
                ],
            ),
        )
