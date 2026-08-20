from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.models.integration import Integration

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercadopago import (
    MercadoPagoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.mercado_pago import (
    MISSING_ACCESS_TOKEN_ERROR,
    MercadoPagoResumeConfig,
    mercado_pago_source,
    validate_credentials as validate_mercado_pago_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

MISSING_INTEGRATION_ERROR = "Missing Mercado Pago integration ID"
INTEGRATION_TOKEN_MISSING_ERROR = "Mercado Pago access token not found"

# Space separated, matching the OAuth `scope` parameter, so the frontend can diff it against what
# the seller actually granted.
REQUIRED_SCOPES = "offline_access read"


@SourceRegistry.register
class MercadoPagoSource(ResumableSource[MercadoPagoSourceConfig, MercadoPagoResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # No pinnable API version: `/v1/payments` sits alongside unversioned `/preapproval` and
    # `/merchant_orders`, and neither is a documented version choice.
    api_docs_url = "https://www.mercadopago.com.br/developers/en/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MERCADOPAGO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MERCADO_PAGO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Mercado Pago (Mercado Libre)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["mercadopago", "mercado libre", "pix", "boleto"],
            caption="""Sync your Mercado Pago payments, merchant orders, and subscriptions into the PostHog Data warehouse.

Connect your Mercado Pago account and approve the read and offline access permissions. PostHog then keeps the connection refreshed for you.

You can also paste a production access token instead, copied from **Your integrations > your application > Production credentials** in the [Mercado Pago developer panel](https://www.mercadopago.com/developers/panel). Access tokens expire and need replacing by hand.

Payments search only covers the last 12 months, so older payments can't be backfilled.""",
            iconPath="/static/services/mercado_pago.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mercado-pago",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="oauth",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Connect Mercado Pago",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="mercado_pago_integration_id",
                                            label="Mercado Pago account",
                                            required=False,
                                            kind="mercado-pago",
                                            requiredScopes=REQUIRED_SCOPES,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Access token",
                                value="access_token",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="access_token",
                                            label="Access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="APP_USR-...",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.mercadopago.com": "Your Mercado Pago credentials are invalid or expired. Reconnect your Mercado Pago account, or paste a new access token.",
            "403 Client Error: Forbidden for url: https://api.mercadopago.com": "Your Mercado Pago credentials are not authorized to read this data. Grant read access and reconnect.",
            # Deterministic config errors — retrying can't fix a credential that was never entered
            # or an integration row that no longer exists. Match on the stable prefix so the
            # volatile integration ID in the mixin's message is ignored.
            MISSING_ACCESS_TOKEN_ERROR: "No Mercado Pago access token is configured. Please update the source configuration.",
            MISSING_INTEGRATION_ERROR: "Mercado Pago is not connected. Please connect your Mercado Pago account.",
            INTEGRATION_TOKEN_MISSING_ERROR: "The Mercado Pago access token is missing. Please reconnect your Mercado Pago account.",
            "Integration not found": "The linked Mercado Pago integration no longer exists. Please reconnect your Mercado Pago account.",
        }

    def _resolve_access_token(self, config: MercadoPagoSourceConfig, team_id: int) -> str:
        """The bearer token for the selected auth method.

        For the connected account, `OauthIntegration.refresh_access_token()` and the scheduled
        refresh in `posthog/tasks/integrations.py` keep this fresh, so the stored token is read
        as-is rather than minted here.
        """
        if config.auth_method.selection == "access_token":
            if not config.auth_method.access_token:
                raise ValueError(MISSING_ACCESS_TOKEN_ERROR)
            return config.auth_method.access_token

        integration_id = config.auth_method.mercado_pago_integration_id
        if not integration_id:
            raise ValueError(MISSING_INTEGRATION_ERROR)

        integration = self.get_oauth_integration(integration_id, team_id)
        # The lookup only scopes to the team, so a hand-crafted config could point at any of the
        # team's integrations and have its token sent to api.mercadopago.com. Only a Mercado Pago
        # grant may be used here.
        if integration.kind != Integration.IntegrationKind.MERCADO_PAGO:
            raise ValueError(f"Integration not found: {integration_id}")
        if not integration.access_token:
            raise ValueError(INTEGRATION_TOKEN_MISSING_ERROR)
        return integration.access_token

    def get_schemas(
        self,
        config: MercadoPagoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MercadoPagoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._resolve_access_token(config, team_id)
        except ValueError as e:
            # The mixin's "Integration not found" wording is developer-facing and carries a
            # volatile integration ID, so reuse the curated messages from get_non_retryable_errors
            # rather than surfacing the raw string in the wizard.
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

        return validate_mercado_pago_credentials(access_token, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MercadoPagoResumeConfig]:
        return ResumableSourceManager[MercadoPagoResumeConfig](inputs, MercadoPagoResumeConfig)

    def source_for_pipeline(
        self,
        config: MercadoPagoSourceConfig,
        resumable_source_manager: ResumableSourceManager[MercadoPagoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Mercado Pago schema '{inputs.schema_name}'")

        return mercado_pago_source(
            access_token=self._resolve_access_token(config, inputs.team_id),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
