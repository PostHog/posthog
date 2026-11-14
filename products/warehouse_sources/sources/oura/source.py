from typing import Optional, cast

from products.warehouse_sources.sources.oura._config import OuraSourceConfig
from products.warehouse_sources.sources.oura.oura import OuraResumeConfig, oura_source, probe_endpoint
from products.warehouse_sources.sources.oura.settings import ENDPOINTS, INCREMENTAL_FIELDS, OURA_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    IntegrationKind,
    OauthIntegration,
    OAuthMixin,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldOauthConfig,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)


@SourceRegistry.register
class OuraSource(OAuthMixin, ResumableSource[OuraSourceConfig, OuraResumeConfig]):
    codebase_detection = detect(env=("^OURA_",))

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://cloud.ouraring.com/v2/docs"

    # Sources created before OAuth stored a personal access token in a `token` row of the `oura` kind.
    # The OAuth account lives in the `oura-ring` kind, so the old rows keep their kind and auth type.
    @property
    def credential_kind(self) -> str | None:
        return "oura"

    @property
    def credential_auth_type(self) -> str:
        return "token"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OURA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OURA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Oura",
            releaseStatus=ReleaseStatus.BETA,
            caption="Connect your Oura account to pull your Oura Ring health data into the PostHog Data warehouse.",
            iconPath="/static/services/oura.png",
            docsUrl="https://posthog.com/docs/cdp/sources/oura",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="oura_integration_id",
                        label="Oura account",
                        required=True,
                        kind="oura-ring",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential/scope problem, so stop the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.ouraring.com": "Oura rejected the access token. Reconnect your Oura account.",
            "403 Client Error: Forbidden for url: https://api.ouraring.com": "Oura denied access to this data. Reconnect your Oura account and allow this data type, or check that your Oura membership is active.",
            # Sources created with a personal access token, which Oura no longer accepts, hold no
            # Oura integration, and neither does a source whose integration was deleted.
            "Integration not found": "Your Oura account is not connected. Reconnect your Oura account.",
            "Oura app not configured": "The Oura app is not configured on this PostHog instance. Contact support.",
        }

    def _get_access_token(self, config: OuraSourceConfig, team_id: int) -> str:
        integration = self.get_oauth_integration(config.oura_integration_id, team_id)
        # The lookup only scopes to the team. Reject an integration of another provider before its
        # token is read or refreshed, so that token is never sent to the Oura API.
        if integration.kind != IntegrationKind.OURA_RING:
            raise ValueError(f"Integration not found: {config.oura_integration_id}")

        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            integration = oauth_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("Oura access token not found")
        return integration.access_token

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.oura.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OuraSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only endpoints with incremental fields (i.e. a server-side date filter) sync
        # incrementally; the others (personal_info, ring_configuration) are full refresh only.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: OuraSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        # Probe the requested endpoint when validating a specific schema, otherwise the cheap
        # single-document personal_info endpoint at source-create.
        try:
            access_token = self._get_access_token(config, team_id)
        except Exception as e:
            return False, str(e)

        path = OURA_ENDPOINTS[schema_name].path if schema_name in OURA_ENDPOINTS else "/usercollection/personal_info"
        status = probe_endpoint(access_token, path)

        if status == 200:
            return True, None
        if status == 401:
            return False, "Oura rejected the access token. Reconnect your Oura account."
        # A valid token can legitimately lack scope for an endpoint the user isn't trying to sync;
        # accept 403 at source-create and only reject it when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status == 403:
            return False, f"Oura denied access to {schema_name}. Reconnect your Oura account and allow this data type."

        return False, "Could not validate the Oura connection"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OuraResumeConfig]:
        return ResumableSourceManager[OuraResumeConfig](inputs, OuraResumeConfig)

    def source_for_pipeline(
        self,
        config: OuraSourceConfig,
        resumable_source_manager: ResumableSourceManager[OuraResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return oura_source(
            token=self._get_access_token(config, inputs.team_id),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
