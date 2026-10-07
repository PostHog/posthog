from posthog.schema import NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from .attribution_table_query_runner import MarketingAnalyticsAttributionQueryRunner
from .constants import INTEGRATION_PRIMARY_SOURCE


class SearchConversionQueryRunner(MarketingAnalyticsAttributionQueryRunner):
    search_keys: list[str]

    @staticmethod
    def row_key(page: str | None, platform: str) -> str:
        return f"{platform}:{page or ''}"

    def _breakdown_expr(self) -> ast.Expr:
        return parse_expr(
            """
            concat(
                multiIf(
                    events.session.$channel_type = 'Paid Search'
                        AND ({source} = {google} OR notEmpty(ifNull(events.session.$entry_gclid, ''))), 'GoogleAds',
                    events.session.$channel_type = 'Organic Search'
                        AND match(lower(ifNull(events.session.$entry_referring_domain, '')), {google_domain}),
                        'GoogleSearchConsole',
                    ''
                ),
                ':', cutQueryStringAndFragment(ifNull(events.session.$entry_current_url, ''))
            )
            """,
            placeholders={
                "source": self._normalized_source_expr(ast.Field(chain=["events", "session", "$entry_utm_source"])),
                "google": ast.Constant(value=INTEGRATION_PRIMARY_SOURCE[NativeMarketingSource.GOOGLE_ADS]),
                "google_domain": ast.Constant(value=r"(^|\.)google\.[a-z.]+$"),
            },
        )

    def _build_outer_select(self) -> ast.SelectQuery:
        query = super()._build_outer_select()
        # Filter after attribution so other channels keep their share of conversion credit.
        query.where = parse_expr(
            "breakdown_value IN {keys}",
            placeholders={"keys": ast.Tuple(exprs=[ast.Constant(value=key) for key in self.search_keys])},
        )
        return query

    def to_query(self) -> ast.SelectQuery:
        # The optimized session reader has no full landing URL or composite breakdown.
        self._live_session_resolution_eligible = False
        return super().to_query()
