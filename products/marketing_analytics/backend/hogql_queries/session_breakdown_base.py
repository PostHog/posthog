"""What a marketing dimension means when it is read off a session, shared by every surface that slices
events by one.

The attribution runners and the retention explorer all answer "which channel/source/campaign does this
event belong to?" the same way: through the `events.session` lazy join, with the team's own source and
campaign aliasing applied, and with the same idea of what counts as naming nothing. Keeping that here is
what stops a channel row on one tab from meaning something different than the identically-named row on
another.
"""

from typing import Generic

from posthog.schema import (
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionPathsQuery,
    MarketingAnalyticsAttributionQuery,
    MarketingAnalyticsRetentionQuery,
)

from posthog.hogql import ast

from .constants import DIRECT_REFERRING_DOMAIN, UNKNOWN_CHANNEL
from .marketing_analytics_base_query_runner import MarketingAnalyticsBaseQueryRunner, ResponseType

# Session field backing each breakdown. Read through the events->sessions lazy join, so a team on
# sessions v2 or v3 gets whichever version its modifiers select.
BREAKDOWN_SESSION_FIELDS: dict[MarketingAnalyticsAttributionBreakdown, str] = {
    MarketingAnalyticsAttributionBreakdown.CHANNEL: "$channel_type",
    MarketingAnalyticsAttributionBreakdown.SOURCE: "$entry_utm_source",
    MarketingAnalyticsAttributionBreakdown.CAMPAIGN: "$entry_utm_campaign",
    MarketingAnalyticsAttributionBreakdown.MEDIUM: "$entry_utm_medium",
    MarketingAnalyticsAttributionBreakdown.CONTENT: "$entry_utm_content",
    MarketingAnalyticsAttributionBreakdown.TERM: "$entry_utm_term",
    MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN: "$entry_referring_domain",
    MarketingAnalyticsAttributionBreakdown.LANDING_PAGE: "$entry_pathname",
}

# Values a breakdown's session field takes to mean "this session names nothing here", beyond an empty
# value. Lives next to `BREAKDOWN_SESSION_FIELDS` and `_breakdown_expr` on purpose: "is this
# unattributed?" and "what does this render as?" are the same question, and answering them in two
# places is how a breakdown ends up excluding a row it displays under a real-looking name.
UNATTRIBUTED_SESSION_VALUES: dict[MarketingAnalyticsAttributionBreakdown, tuple[str, ...]] = {
    # The classifier's own sentinel for a session it couldn't place. Its other outputs (Organic
    # Search, Direct, Referral) are real classifications and stay.
    MarketingAnalyticsAttributionBreakdown.CHANNEL: (UNKNOWN_CHANNEL,),
    MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN: (DIRECT_REFERRING_DOMAIN,),
}


class MarketingSessionBreakdownQueryRunnerBase(MarketingAnalyticsBaseQueryRunner[ResponseType], Generic[ResponseType]):
    query: (
        MarketingAnalyticsAttributionQuery | MarketingAnalyticsAttributionPathsQuery | MarketingAnalyticsRetentionQuery
    )

    @property
    def breakdown(self) -> MarketingAnalyticsAttributionBreakdown:
        return self.query.breakdownBy or MarketingAnalyticsAttributionBreakdown.CHANNEL

    def _breakdown_expr(self) -> ast.Expr:
        """The dimension a touchpoint reports as, read off the session it belongs to.

        Channel, source and campaign fall back to the same sentinels and normalization the rest of
        marketing analytics uses, so rows line up with the cost side. The remaining breakdowns have no
        team-configurable aliasing to collapse, so they pass the entry field straight through.
        """
        field = ast.Field(chain=["events", "session", BREAKDOWN_SESSION_FIELDS[self.breakdown]])

        if self.breakdown == MarketingAnalyticsAttributionBreakdown.CHANNEL:
            return self._non_empty_or(field, UNKNOWN_CHANNEL)
        if self.breakdown == MarketingAnalyticsAttributionBreakdown.SOURCE:
            return self._normalized_source_expr(field)
        if self.breakdown == MarketingAnalyticsAttributionBreakdown.CAMPAIGN:
            return self._normalized_campaign_expr(field)
        return ast.Call(name="toString", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])

    def _normalized_source_expr(self, field: ast.Expr) -> ast.Expr:
        """Collapse the team's custom UTM source aliases onto each adapter's canonical source name, or
        the events side and the cost side disagree on the row key. Same treatment as `_build_sessions_select`.
        """
        from .adapters.factory import MarketingSourceFactory  # noqa: PLC0415 — avoids an import cycle
        from .utils import build_source_normalization_expr  # noqa: PLC0415 — avoids an import cycle

        source_mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )
        return build_source_normalization_expr(
            self._non_empty_or(field, self.config.organic_source),
            source_mappings,
        )

    def _normalized_campaign_expr(self, field: ast.Expr) -> ast.Expr:
        """Collapse the team's dirty utm_campaign spellings onto the clean name they're mapped to.

        Without this a campaign whose UTMs vary lands as one row per spelling, and because the models
        credit each row independently, first touch can name one spelling while last touch names another
        — the comparison this table exists for then reads as a difference between campaigns that are
        the same campaign. Scoped by source, so the mapping is applied the way the Dashboard applies it.
        """
        from .utils import build_campaign_display_normalization_expr  # noqa: PLC0415 — avoids an import cycle

        raw_campaign = ast.Call(name="toString", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])
        return build_campaign_display_normalization_expr(
            raw_campaign,
            ast.Field(chain=["events", "session", "$entry_utm_source"]),
            self.team.marketing_analytics_config,
        )

    @staticmethod
    def _non_empty_or(field: ast.Expr, fallback: str) -> ast.Expr:
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="notEmpty", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])]),
                field,
                ast.Constant(value=fallback),
            ],
        )

    def _pageview_condition(self) -> ast.Expr:
        return ast.CompareOperation(
            left=ast.Field(chain=["events", "event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value="$pageview"),
        )

    def _touchpoint_condition(self) -> ast.Expr:
        """A pageview inside a real session counts as a touchpoint.

        Both exclusions are applied here — before any credit is computed — so the remaining touchpoints
        renormalize to full credit instead of quietly losing the excluded share.
        """
        conditions: list[ast.Expr] = [
            self._pageview_condition(),
            ast.Call(name="notEmpty", args=[ast.Field(chain=["events", "$session_id"])]),
            # A session id that resolves to no session row yields epoch zero rather than null, because the
            # join fills a non-nullable column with its default. Test for a real timestamp rather than for
            # null: 1970 can never satisfy the attribution window, so such a touchpoint earns nothing, and
            # left in place it would sort to the very front and consume truncation slots. When a
            # conversion's own session is one of these, dropping it here is what keeps the conversion out
            # of the attributed count instead of silently crediting nobody.
            ast.CompareOperation(
                left=ast.Call(
                    name="toUnixTimestamp", args=[ast.Field(chain=["events", "session", "$start_timestamp"])]
                ),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            ),
        ]
        if self.query.excludeDirectTraffic:
            conditions.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "session", "$channel_type"]),
                    op=ast.CompareOperationOp.NotEq,
                    right=ast.Constant(value="Direct"),
                )
            )
        if self.query.excludeUnattributed:
            # A touchpoint is unattributed when the session names nothing for the current breakdown:
            # an empty value, or one of the sentinels that breakdown substitutes for "don't know".
            # Judged on the raw session field rather than the display expression, so a friendly
            # fallback label can't smuggle an empty value back in.
            #
            # Which is why channel and source deliberately part ways on the same untagged session:
            # `$channel_type` runs a classifier that places it in a real bucket (Organic Search,
            # Direct, Referral), so only the classifier's own `Unknown` counts as unattributed.
            # `$entry_utm_source` has no classifier — an empty value there is the plain absence of a
            # source, which `_breakdown_expr` merely *labels* `organic`, so it is excluded.
            field = ast.Field(chain=["events", "session", BREAKDOWN_SESSION_FIELDS[self.breakdown]])
            conditions.append(
                ast.Call(name="notEmpty", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])
            )
            for sentinel in UNATTRIBUTED_SESSION_VALUES.get(self.breakdown, ()):
                conditions.append(
                    ast.CompareOperation(
                        left=field,
                        op=ast.CompareOperationOp.NotEq,
                        right=ast.Constant(value=sentinel),
                    )
                )
        return ast.And(exprs=conditions)
