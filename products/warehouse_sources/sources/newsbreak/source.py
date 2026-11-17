from typing import Optional, cast

from products.warehouse_sources.sources.newsbreak._config import NewsBreakSourceConfig
from products.warehouse_sources.sources.newsbreak.newsbreak import (
    INVALID_TIMEZONE_ERROR,
    INVALID_TOKEN_ERROR,
    NO_ORGANIZATIONS_ERROR,
    PERMISSION_ERROR,
    NewsBreakReportCursor,
    NewsBreakResumeConfig,
    newsbreak_source,
    validate_credentials as validate_newsbreak_credentials,
)
from products.warehouse_sources.sources.newsbreak.settings import ENDPOINTS, INCREMENTAL_FIELDS, REPORT_LOOKBACK_DAYS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    CursorSource,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceCursorManager,
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

SOURCE_KEY = "NewsBreak"


@SourceRegistry.register
class NewsBreakSource(
    ResumableSource[NewsBreakSourceConfig, NewsBreakResumeConfig], CursorSource[NewsBreakReportCursor]
):
    # The NewsBreak pixel loads from this host.
    codebase_detection = detect(script_hosts=("static.newsbreak.com",))

    lists_tables_without_credentials = True  # Static endpoint catalog, safe for public docs.
    # `/business-api/v1` is the only version, and NewsBreak documents no other.
    api_docs_url = "https://advertising-api.newsbreak.com/hc/en-us"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_kind(self) -> str:
        # The kebab-case default splits the brand name into "news-break".
        return "newsbreak"

    def cursor_class(self) -> type[NewsBreakReportCursor]:
        return NewsBreakReportCursor

    def merge_cursors(self, current: NewsBreakReportCursor, candidate: NewsBreakReportCursor) -> NewsBreakReportCursor:
        return NewsBreakReportCursor(
            backfilled_account_ids=tuple(
                sorted(set(current.backfilled_account_ids) | set(candidate.backfilled_account_ids))
            )
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict.fromkeys(
            (INVALID_TOKEN_ERROR, PERMISSION_ERROR, NO_ORGANIZATIONS_ERROR, INVALID_TIMEZONE_ERROR), None
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.newsbreak.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: NewsBreakSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Reports read recent days again, so append would add a second row for each of them.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=INCREMENTAL_FIELDS.keys(),
            default_incremental_lookback_seconds=dict.fromkeys(INCREMENTAL_FIELDS, REPORT_LOOKBACK_DAYS * 24 * 60 * 60),
        )

    def validate_credentials(
        self,
        config: NewsBreakSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_newsbreak_credentials(config.access_token, config.org_ids, config.report_timezone)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NewsBreakResumeConfig]:
        return ResumableSourceManager[NewsBreakResumeConfig](inputs, NewsBreakResumeConfig)

    def source_for_pipeline(
        self,
        config: NewsBreakSourceConfig,
        resumable_source_manager: ResumableSourceManager[NewsBreakResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return newsbreak_source(
            access_token=config.access_token,
            org_ids=config.org_ids,
            report_timezone=config.report_timezone,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            cursor_manager=cast(Optional[SourceCursorManager[NewsBreakReportCursor]], inputs.source_cursor),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="NewsBreak Ads",
            keywords=["newsbreak", "news break"],
            caption=(
                "Sync your NewsBreak ad accounts, campaigns, ad sets, ads and daily performance reports "
                "(spend, impressions, clicks, conversions, conversion value and ROAS). Generate an access token "
                "in NewsBreak Ads Manager under **Tools > Resources > API Access Tokens**."
            ),
            iconPath="/static/warehouse-sources/newsbreak/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/newsbreak",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="org_ids",
                        label="Organization IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="123456, 234567",
                        caption=(
                            "Optional. Separate IDs with commas. Leave empty to sync every organization "
                            "where you're an admin."
                        ),
                        secret=False,
                        account_selector=True,
                    ),
                    SourceFieldInputConfig(
                        name="report_timezone",
                        label="Report time zone",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="UTC",
                        caption="Optional. The time zone that report dates use, such as `America/New_York`. Defaults to UTC.",
                        secret=False,
                        sync_setting=True,
                    ),
                ],
            ),
        )
