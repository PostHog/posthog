from typing import Optional, cast

from products.warehouse_sources.sources.helpin._config import HelpinSourceConfig
from products.warehouse_sources.sources.helpin.helpin import (
    HelpinResumeConfig,
    api_hostname,
    endpoint_permissions,
    helpin_source,
    normalize_api_host,
    validate_credentials as validate_helpin_credentials,
)
from products.warehouse_sources.sources.helpin.settings import ENDPOINTS, HELPIN_CLOUD_API_HOST, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    ValidateDatabaseHostMixin,
    build_endpoint_schemas,
    detect,
    source_key,
)

SOURCE_KEY = "Helpin"


@SourceRegistry.register
class HelpinSource(ResumableSource[HelpinSourceConfig, HelpinResumeConfig], ValidateDatabaseHostMixin):
    codebase_detection = detect(
        npm=("@helpin-ai/sdk-js", "@helpin-ai/react", "@helpin-ai/vue", "@helpin-ai/nextjs"),
        script_hosts=("cdn.helpin.ai",),
    )

    # The REST API has one version, carried in the `/public/v1` path, with no documented version choice.
    api_docs_url = "https://docs.helpin.ai/articles/helpin-rest-api-8a892e5f"

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_auth_type(self) -> str:
        # Frozen as "credentials" in credential_auth_types.py while the source was a stub with no fields.
        return "credentials"

    @property
    def connection_host_fields(self) -> list[str]:
        # `api_host` decides where the stored token is sent, so changing it must re-require the token.
        return ["api_host"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Helpin",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Sync your Helpin support conversations, CRM records, tasks, planning and docs into the PostHog Data warehouse.

In Helpin, a workspace manager creates an automation account under **Settings > MCP access > Service accounts**, then creates a token for it. The token starts with `hmp_` and is shown once. Give the account read scopes for the tables you want:

- `helpin.support.read`: support conversations, messages, inboxes and tags
- `helpin.crm.read`: contacts, companies, deals and pipelines
- `helpin.pm.read`: tasks, epics, sprints, objectives, labels and workflows
- `helpin.docs.read`: documents
- `helpin.context.read`: teams and members

The account can be read-only. Leave the API host blank for Helpin Cloud. For a self-hosted Helpin, enter your API host. It must use https.
""",
            iconPath="/static/warehouse-sources/helpin/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/helpin",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="hmp_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="api_host",
                        label="API host (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=HELPIN_CLOUD_API_HOST,
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.helpin.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Helpin didn't accept your token. Create a new token for the automation account in Helpin, then reconnect the source.",
            "403 Client Error: Forbidden": "Your Helpin token can't read this table. Give the automation account the read scope for it in Helpin, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: HelpinSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def _checked_base_url(self, config: HelpinSourceConfig, team_id: int) -> str:
        base_url = normalize_api_host(config.api_host)
        host_valid, host_error = self.is_database_host_valid(api_hostname(config.api_host), team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Helpin API host")
        return base_url

    def validate_credentials(
        self,
        config: HelpinSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            base_url = self._checked_base_url(config, team_id)
        except ValueError as e:
            return False, str(e)
        return validate_helpin_credentials(base_url, config.api_token, schema_name)

    def get_endpoint_permissions(
        self, config: HelpinSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        try:
            base_url = self._checked_base_url(config, team_id)
        except ValueError:
            return dict.fromkeys(endpoints)
        return endpoint_permissions(base_url, config.api_token, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HelpinResumeConfig]:
        return ResumableSourceManager[HelpinResumeConfig](inputs, HelpinResumeConfig)

    def source_for_pipeline(
        self,
        config: HelpinSourceConfig,
        resumable_source_manager: ResumableSourceManager[HelpinResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return helpin_source(
            base_url=self._checked_base_url(config, inputs.team_id),
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
