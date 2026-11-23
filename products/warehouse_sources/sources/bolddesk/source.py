from typing import Optional, cast

from products.warehouse_sources.sources.bolddesk._config import BoldDeskSourceConfig
from products.warehouse_sources.sources.bolddesk.bolddesk import (
    BoldDeskResumeConfig,
    InvalidBoldDeskDomainError,
    bolddesk_source,
    validate_credentials as validate_bolddesk_credentials,
)
from products.warehouse_sources.sources.bolddesk.settings import BOLDDESK_ENDPOINTS, ENDPOINTS, INCREMENTAL_FIELDS
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
    build_endpoint_schemas,
    detect,
    source_key,
)

SOURCE_KEY = "BoldDesk"


@SourceRegistry.register
class BoldDeskSource(ResumableSource[BoldDeskSourceConfig, BoldDeskResumeConfig]):
    # The chat widget script loads from the account's own <subdomain>.bolddesk.com host.
    codebase_detection = detect(script_hosts=("bolddesk.com",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # BoldDesk has one REST API version, the `/api/v1` path segment.
    api_docs_url = "https://developer.bolddesk.com/api"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_kind(self) -> str | None:
        return "bolddesk"

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<domain>.bolddesk.com`, so a changed domain must ask for the key again.
        return ["domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="BoldDesk",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your BoldDesk subdomain and an API key to import your BoldDesk help desk data.

Create the API key in BoldDesk under **Profile → API keys** (`https://yourcompany.bolddesk.com/agent/personal-settings`). The key reads the same tickets and records as the agent who created it. If you use a custom domain, enter your `bolddesk.com` subdomain.""",
            iconPath="/static/warehouse-sources/bolddesk/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bolddesk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="domain",
                        label="BoldDesk subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
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
            "401 Client Error: Unauthorized for url": "BoldDesk rejected your API key. Create a new API key in BoldDesk, then reconnect the source.",
            "403 Client Error: Forbidden for url": "Your BoldDesk API key can't read this table. Use a key from an agent who has access to this data, then reconnect the source.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.bolddesk.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BoldDeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BoldDeskSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in BOLDDESK_ENDPOINTS:
            return False, f"Unknown BoldDesk table: {schema_name}"
        try:
            ok, status_code = validate_bolddesk_credentials(config.domain, config.api_key, schema_name or "tickets")
        except InvalidBoldDeskDomainError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "BoldDesk rejected the API key. Check the key and try again."
        # A 403 means the key is valid but its agent can't read tickets. The agent can still read
        # other tables, so only the check for one table fails on it.
        if status_code == 403 and schema_name is None:
            return True, None
        if status_code == 403:
            return False, "Your BoldDesk API key doesn't have access to this data."
        return False, "Could not connect to BoldDesk. Check the subdomain and API key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BoldDeskResumeConfig]:
        return ResumableSourceManager[BoldDeskResumeConfig](inputs, BoldDeskResumeConfig)

    def source_for_pipeline(
        self,
        config: BoldDeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[BoldDeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bolddesk_source(
            domain=config.domain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
