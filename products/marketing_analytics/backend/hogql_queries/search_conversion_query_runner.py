from posthog.schema import MarketingAnalyticsAttributionBreakdown, NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from .attribution_base import PERSON_ARRAYS_CTE
from .attribution_sessions_read import session_ctes
from .attribution_table_query_runner import _WEIGHT_ALIASES, MarketingAnalyticsAttributionQueryRunner
from .constants import INTEGRATION_PRIMARY_SOURCE


class SearchConversionQueryRunner(MarketingAnalyticsAttributionQueryRunner):
    search_keys: list[str]

    @staticmethod
    def row_key(value: str | None, platform: str) -> str:
        return f"{platform}:{value or ''}"

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
        by_keyword = self.query.breakdownBy == MarketingAnalyticsAttributionBreakdown.TERM
        value = (
            parse_expr("lower(trim(ifNull({term}, '')))", placeholders={"term": field("utm_term", "$entry_utm_term")})
            if by_keyword
            else parse_expr("cutQueryStringAndFragment(ifNull({url}, ''))", placeholders={"url": url})
        )
        return parse_expr(
            """
            concat(
                multiIf(
                    {channel} = 'Paid Search' AND ({source} = {google} OR {has_gclid}), 'GoogleAds',
                    {channel} = 'Paid Search' AND ({source} = {bing} OR {has_msclkid}), 'BingAds',
                    {include_organic} AND {channel} = 'Organic Search' AND NOT {has_msclkid}
                        AND match(lower(ifNull({referrer}, '')), {google_domain}), 'GoogleSearchConsole',
                    ''
                ),
                ':', {value}
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
                "include_organic": ast.Constant(value=not by_keyword),
                "value": value,
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

    def to_conversion_query(self) -> ast.SelectQuery:
        model = self.config.attribution_mode
        query = parse_select(
            """
            SELECT credit.1 AS breakdown_value, sum(credit.2) AS conversions
            FROM {conversions}
            ARRAY JOIN arrayZip(dims, {weights}) AS credit
            WHERE credit.1 IN {keys}
            GROUP BY breakdown_value
            """,
            placeholders={
                "conversions": self._build_per_conversion_select(model=model),
                "weights": ast.Field(chain=[_WEIGHT_ALIASES[model]]),
                "keys": ast.Tuple(exprs=[ast.Constant(value=key) for key in self.search_keys]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        query.ctes = session_ctes(self, self.query_date_range)
        query.ctes[PERSON_ARRAYS_CTE] = ast.CTE(
            name=PERSON_ARRAYS_CTE, expr=self._person_arrays_select(self.query_date_range), cte_type="subquery"
        )
        return query

    def calculate_conversions(self) -> dict[str, float]:
        # Search needs credit only; visitor reach and report totals would add unused event scans.
        query = self.to_conversion_query()
        response = execute_hogql_query(
            query_type="marketing_analytics_search_conversions_query",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context or LimitContext.QUERY,
            context=self._shared_hogql_context,
            settings=self.get_query_settings(),
        )
        return {str(key): float(conversions) for key, conversions in response.results or []}
