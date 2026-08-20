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

from products.warehouse_sources.backend.temporal.data_imports.sources.clover.clover import (
    CloverResumeConfig,
    clover_source,
    endpoint_permissions as clover_endpoint_permissions,
    validate_credentials as validate_clover_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.oauth import (
    CloverIntegrationAuth,
    resolve_clover_oauth_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.settings import (
    CLOVER_INTEGRATION_KIND_REGIONS,
    CLOVER_REGION_INTEGRATION_KINDS,
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    AuthConfigBase,
    BearerTokenAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clover import CloverSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Region is baked into the OAuth options rather than offered as its own dropdown: a Clover app is
# registered per region and can only authorize merchants there, so the region is what decides which
# PostHog OAuth app the Connect button uses. One option per region keeps that binding explicit and
# the form one level deep.
_OAUTH_REGION_OPTIONS: dict[str, str] = {
    "oauth_na": "na",
    "oauth_eu": "eu",
    "oauth_latam": "latam",
    "oauth_sandbox": "sandbox",
}

_REGION_LABELS = {
    "na": "North America",
    "eu": "Europe",
    "latam": "Latin America",
    "sandbox": "sandbox",
}


def _oauth_option(selection: str, region: str) -> SourceFieldSelectConfigOption:
    return SourceFieldSelectConfigOption(
        label=f"Connect Clover ({_REGION_LABELS[region]})",
        value=selection,
        fields=cast(
            list[FieldType],
            [
                SourceFieldOauthConfig(
                    name="clover_integration_id",
                    label="Clover account",
                    required=False,
                    kind=CLOVER_REGION_INTEGRATION_KINDS[region],
                ),
            ],
        ),
    )


def _api_token_option() -> SourceFieldSelectConfigOption:
    return SourceFieldSelectConfigOption(
        label="API token",
        value="api_token",
        fields=cast(
            list[FieldType],
            [
                SourceFieldSelectConfig(
                    name="region",
                    label="Region",
                    required=True,
                    defaultValue=DEFAULT_REGION,
                    options=[
                        SourceFieldSelectConfigOption(label=_REGION_LABELS[region].capitalize(), value=region)
                        for region in CLOVER_REGION_INTEGRATION_KINDS
                    ],
                ),
                SourceFieldInputConfig(
                    name="merchant_id",
                    label="Merchant ID",
                    type=SourceFieldInputConfigType.TEXT,
                    required=False,
                    placeholder="",
                    secret=False,
                ),
                SourceFieldInputConfig(
                    name="api_token",
                    label="API token",
                    type=SourceFieldInputConfigType.PASSWORD,
                    required=False,
                    placeholder="",
                    secret=True,
                ),
            ],
        ),
    )


@SourceRegistry.register
class CloverSource(ResumableSource[CloverSourceConfig, CloverResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.clover.com/dev/reference/api-reference-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOVER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOVER,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            keywords=["pos", "point of sale", "fiserv"],
            label="Clover",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync orders, payments, refunds, inventory and customers from a Clover merchant into the PostHog Data warehouse.

Pick the Clover region your business is in, then click Connect and authorize PostHog. Clover tells us which merchant you authorized, so there is nothing else to fill in. If you would rather not connect the app, choose API token and enter a merchant ID plus an API token generated for it in the Clover dashboard.

You need to grant read access for every entity you want to sync, such as orders, payments and inventory. Tables you have not granted are flagged in the table picker.""",
            iconPath="/static/services/clover.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clover",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_type",
                        label="Authentication",
                        required=True,
                        defaultValue="oauth_na",
                        options=[
                            *(_oauth_option(selection, region) for selection, region in _OAUTH_REGION_OPTIONS.items()),
                            _api_token_option(),
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Clover rejected your credentials. Reconnect your Clover account, or generate a new API token and update the source.",
            "403 Client Error: Forbidden for url": "Your Clover connection is missing read access for this table. Grant it in the Clover dashboard and sync again.",
            # Deterministic credential/config errors from OAuthMixin and the auth builder — the
            # integration row is gone or unconfigured, so retrying can never succeed. Match on the
            # stable prefix so the volatile integration ID is ignored.
            "Missing Clover integration ID": "Clover is not connected. Reconnect your Clover account.",
            "Integration not found": "The linked Clover integration no longer exists. Reconnect your Clover account.",
            "Clover access token not found": "The Clover access token is missing. Reconnect your Clover account.",
            "Clover integration is missing a merchant ID": "The Clover connection did not record a merchant. Reconnect your Clover account.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clover.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloverSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Merge only: a resumed run re-fetches the page it checkpointed on, and consecutive filter
        # windows share their boundary millisecond, so append mode would duplicate those rows.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def _connection(self, config: CloverSourceConfig, team_id: int) -> tuple[str, str, AuthConfigBase]:
        """Resolve (region, merchant id, transport auth) for the selected auth method.

        On the OAuth path the region comes from the integration's kind rather than the form: the
        kind is what pins the Clover app and host the token was issued against, so trusting it keeps
        a stale or hand-edited region in the stored config from pointing a token at another region.
        """
        auth_type = config.auth_type
        if auth_type.selection == "api_token":
            if not auth_type.api_token:
                raise ValueError("Missing Clover API token")
            if not auth_type.merchant_id:
                raise ValueError("Missing Clover merchant ID")
            return auth_type.region, auth_type.merchant_id, BearerTokenAuth(auth_type.api_token)

        integration_id = auth_type.clover_integration_id
        if not integration_id:
            raise ValueError("Missing Clover integration ID")
        integration = self.get_oauth_integration(integration_id, team_id)
        region = CLOVER_INTEGRATION_KIND_REGIONS.get(integration.kind)
        if region is None:
            raise ValueError(f"Integration {integration_id} is not a Clover integration")
        merchant_id = (integration.config or {}).get("merchant_id")
        if not merchant_id:
            raise ValueError("Clover integration is missing a merchant ID")

        token = resolve_clover_oauth_token(integration_id, team_id)
        return region, merchant_id, CloverIntegrationAuth(integration_id, team_id, token)

    def validate_credentials(
        self,
        config: CloverSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            region, merchant_id, auth = self._connection(config, team_id)
        except ValueError as e:
            # These are deterministic config/credential errors whose developer wording is unhelpful
            # in the wizard and can carry a volatile integration ID. Reuse the curated messages from
            # get_non_retryable_errors; fall back to the raw message if unmapped.
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

        return validate_clover_credentials(
            region=region,
            merchant_id=merchant_id,
            auth=auth,
            # At source-create a 403 only means the merchant hasn't granted that entity, which must
            # not block connecting; a per-schema check is asking about that entity specifically.
            accept_forbidden=schema_name is None,
        )

    def get_endpoint_permissions(
        self,
        config: CloverSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        try:
            region, merchant_id, auth = self._connection(config, team_id)
        except ValueError:
            # A misconfigured connection is reported by validate_credentials; per-table access must
            # never block the schema picker, so report everything reachable here.
            return dict.fromkeys(endpoints)

        return clover_endpoint_permissions(
            region=region,
            merchant_id=merchant_id,
            endpoints=endpoints,
            auth=auth,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloverResumeConfig]:
        return ResumableSourceManager[CloverResumeConfig](inputs, CloverResumeConfig)

    def source_for_pipeline(
        self,
        config: CloverSourceConfig,
        resumable_source_manager: ResumableSourceManager[CloverResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        region, merchant_id, auth = self._connection(config, inputs.team_id)
        return clover_source(
            region=region,
            merchant_id=merchant_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            auth=auth,
            incremental_field=inputs.incremental_field,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
