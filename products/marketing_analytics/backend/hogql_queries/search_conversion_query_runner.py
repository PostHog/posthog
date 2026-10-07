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

    def additional_session_columns(self) -> set[str]:
        return {"channel_type", "utm_source", "referring_domain", "entry_url", "has_gclid", "has_msclkid"}

    def _search_breakdown_expr(self, *, resolved: bool) -> ast.Expr:
        def field(column: str, session_field: str) -> ast.Expr:
            return ast.Field(chain=[column] if resolved else ["events", "session", session_field])

        url = field("entry_url", "$entry_current_url")
        if resolved:
            has_gclid: ast.Expr = ast.Field(chain=["has_gclid"])
            has_msclkid: ast.Expr = ast.Field(chain=["has_msclkid"])
        else:
            has_gclid = parse_expr("notEmpty(ifNull(events.session.$entry_gclid, ''))")
            has_msclkid = parse_expr(
                "notEmpty(ifNull(events.session.$entry_msclkid, '')) OR notEmpty(extractURLParameter(ifNull({url}, ''), 'msclkid'))",
                placeholders={"url": url},
            )
        return parse_expr(
            """
            concat(
                multiIf(
                    {channel} = 'Paid Search' AND ({source} = {google} OR {has_gclid}), 'GoogleAds',
                    {channel} = 'Paid Search' AND ({source} = {bing} OR {has_msclkid}), 'BingAds',
                    {channel} = 'Organic Search' AND NOT {has_msclkid}
                        AND match(lower(ifNull({referrer}, '')), {google_domain}), 'GoogleSearchConsole',
                    ''
                ),
                ':', cutQueryStringAndFragment(ifNull({url}, ''))
            )
            """,
            placeholders={
                "channel": field("channel_type", "$channel_type"),
                "source": self._normalized_source_expr(
                    ast.Call(name="lower", args=[field("utm_source", "$entry_utm_source")])
                ),
                "google": ast.Constant(value=INTEGRATION_PRIMARY_SOURCE[NativeMarketingSource.GOOGLE_ADS]),
                "bing": ast.Constant(value=INTEGRATION_PRIMARY_SOURCE[NativeMarketingSource.BING_ADS]),
                "has_gclid": has_gclid,
                "has_msclkid": has_msclkid,
                "referrer": field("referring_domain", "$entry_referring_domain"),
                "google_domain": ast.Constant(value=r"(^|\.)google\.[a-z.]+$"),
                "url": url,
            },
        )

    def _breakdown_expr(self) -> ast.Expr:
        return self._search_breakdown_expr(resolved=False)

    def resolved_breakdown_expr(self) -> ast.Expr:
        return self._search_breakdown_expr(resolved=True)

    def _build_outer_select(self) -> ast.SelectQuery:
        query = super()._build_outer_select()
        # Filter after attribution so other channels keep their share of conversion credit.
        query.where = parse_expr(
            "breakdown_value IN {keys}",
            placeholders={"keys": ast.Tuple(exprs=[ast.Constant(value=key) for key in self.search_keys])},
        )
        return query
