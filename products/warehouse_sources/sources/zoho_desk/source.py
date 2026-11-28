from typing import Optional, cast

from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)
from products.warehouse_sources.sources.zoho_desk._config import ZohoDeskSourceConfig
from products.warehouse_sources.sources.zoho_desk.settings import ENDPOINTS, INCREMENTAL_FIELDS, SHOULD_SYNC_DEFAULT
from products.warehouse_sources.sources.zoho_desk.zoho_desk import (
    TOKEN_ERROR_MESSAGES,
    TOKEN_REFRESH_FAILED_PREFIX,
    ZohoDeskResumeConfig,
    validate_credentials as validate_zoho_desk_credentials,
    zoho_desk_source,
)

SCOPE_MISMATCH_MESSAGE = (
    "Your Zoho Desk token is missing the scope for this table. Generate a new refresh token with the scopes "
    "Desk.tickets.READ, Desk.contacts.READ, Desk.accounts.READ, Desk.basic.READ, Desk.products.READ, "
    "Desk.activities.READ, and Desk.contracts.READ, or turn off this table in the source's schema settings."
)
ORGANIZATION_MISMATCH_MESSAGE = (
    "Your Zoho Desk token is linked to a different organization than the organization ID on this source. "
    "Remove the organization ID, or generate a new refresh token and pick that organization when you generate the code."
)
EDITION_LIMIT_MESSAGE = (
    "Your Zoho Desk edition doesn't include this module. Turn off this table in the source's schema settings."
)
UNAUTHORIZED_MESSAGE = (
    "Zoho Desk rejected the access token for this source. Generate a new refresh token from your self client, "
    "then reconnect."
)
FORBIDDEN_MESSAGE = (
    "Zoho Desk denied access to this table. Give your Zoho Desk user permission to view this module, "
    "or turn off this table in the source's schema settings."
)


@SourceRegistry.register
class ZohoDeskSource(ResumableSource[ZohoDeskSourceConfig, ZohoDeskResumeConfig]):
    codebase_detection = detect(env=("^(ZOHO_DESK|ZOHODESK)_",))

    lists_tables_without_credentials = True  # static endpoint catalog, with no request to Zoho
    api_docs_url = "https://desk.zoho.com/DeskAPIDocument"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHODESK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The error code entries come first. An error carries both a status and a code, and the code
        # names the cause more exactly than the status.
        return {
            **{f"{TOKEN_REFRESH_FAILED_PREFIX}: {code}": message for code, message in TOKEN_ERROR_MESSAGES.items()},
            "code=SCOPE_MISMATCH": SCOPE_MISMATCH_MESSAGE,
            "code=OAUTH_ORG_MISMATCH": ORGANIZATION_MISMATCH_MESSAGE,
            "code=LICENSE_ACCESS_LIMITED": EDITION_LIMIT_MESSAGE,
            "code=FORBIDDEN": FORBIDDEN_MESSAGE,
            "401 Client Error": UNAUTHORIZED_MESSAGE,
            "403 Client Error": FORBIDDEN_MESSAGE,
            "Non-JSON response from": "Zoho Desk returned a non-JSON response, for example an HTML error or login page, instead of data. Check that the data center you picked matches your Zoho account, then try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHODESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            keywords=["zoho"],
            label="Zoho Desk",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Connect your Zoho Desk account to pull tickets, contacts, accounts, and your other help desk data into the PostHog Data warehouse.

In the [Zoho API console](https://api-console.zoho.com), create a **Self Client** and generate a code for the scopes `Desk.tickets.READ`, `Desk.contacts.READ`, `Desk.accounts.READ`, `Desk.basic.READ`, `Desk.products.READ`, and `Desk.activities.READ`. To sync contracts, also add `Desk.contracts.READ`. If you have more than one Zoho Desk organization, pick the one to sync when you generate the code. That code is not a refresh token and expires within minutes. Exchange it for a refresh token by sending a POST request to `/oauth/v2/token` on your data center's Zoho accounts domain, with `grant_type=authorization_code`, your client ID, client secret, and the code. Paste the client ID, client secret, and refresh token below, then pick the data center your Zoho account lives in.

Every table is a full refresh, because the Zoho Desk list API can't return only the records that changed. Each request uses Zoho Desk API credits, and requests deep into a large table use more, so pick a sync frequency that fits your daily credit limit.""",
            iconPath="/static/services/zoho_desk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zoho-desk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Data center",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="United States (.com)", value="us"),
                            SourceFieldSelectConfigOption(label="Europe (.eu)", value="eu"),
                            SourceFieldSelectConfigOption(label="United Kingdom (.uk)", value="uk"),
                            SourceFieldSelectConfigOption(label="India (.in)", value="in"),
                            SourceFieldSelectConfigOption(label="Australia (.com.au)", value="au"),
                            SourceFieldSelectConfigOption(label="Japan (.jp)", value="jp"),
                            SourceFieldSelectConfigOption(label="Canada (.ca)", value="ca"),
                            SourceFieldSelectConfigOption(label="Saudi Arabia (.sa)", value="sa"),
                            SourceFieldSelectConfigOption(label="Singapore (.sg)", value="sg"),
                            SourceFieldSelectConfigOption(label="United Arab Emirates (.ae)", value="ae"),
                            SourceFieldSelectConfigOption(label="China (.com.cn)", value="cn"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1000.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="1000.XXXXXXXX.XXXXXXXX",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        caption="Leave this empty unless Zoho Desk asks for an organization ID. Your refresh token is already linked to the organization you picked when you generated the code.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.zoho_desk.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ZohoDeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, should_sync_default=SHOULD_SYNC_DEFAULT)

    def validate_credentials(
        self,
        config: ZohoDeskSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_zoho_desk_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZohoDeskResumeConfig]:
        return ResumableSourceManager[ZohoDeskResumeConfig](inputs, ZohoDeskResumeConfig)

    def source_for_pipeline(
        self,
        config: ZohoDeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZohoDeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zoho_desk_source(
            config=config,
            endpoint_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
