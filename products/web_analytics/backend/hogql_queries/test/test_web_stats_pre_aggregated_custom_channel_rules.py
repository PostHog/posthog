import time_machine
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    CustomChannelCondition,
    CustomChannelField,
    CustomChannelOperator,
    CustomChannelRule,
    DateRange,
    FilterLogicalOperator,
    HogQLQueryModifiers,
    SessionPropertyFilter,
    WebAnalyticsPreComputeStrategy,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL

from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)


def _rule(
    channel_type: str,
    key: CustomChannelField,
    value: str | None,
    op: CustomChannelOperator = CustomChannelOperator.EXACT,
) -> CustomChannelRule:
    return CustomChannelRule(
        channel_type=channel_type,
        combiner=FilterLogicalOperator.AND_,
        id="rule-1",
        items=[CustomChannelCondition(id="condition-1", key=key, op=op, value=value)],
    )


# The pre-aggregated tables hold no entry URL, and their host column is the event host rather than the
# session entry host, so a rule on either field must fall back to the live path.
FIELDS_ABSENT_FROM_PRE_AGGREGATED = [
    ("url", CustomChannelField.URL, "https://example.com/pricing", "Pricing page"),
    ("hostname", CustomChannelField.HOSTNAME, "example.com", "Main site"),
]


class TestWebStatsPreAggregatedCustomChannelRules(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with time_machine.travel("2024-01-01T09:00:00Z", tick=False):
            for index, (pathname, referring_domain, utm_source) in enumerate(
                [
                    # Mixed case on purpose: a rule must match the value as the team wrote it.
                    ("/pricing", "$direct", "MyPartner"),
                    ("/blog", "google.com", None),
                    # The literal string 'null' is a value sites really send.
                    ("/signup", "$direct", "null"),
                    # A link to the bare domain. path() returns '' for it, the same as for a missing
                    # entry URL, so the entry pathname must not treat '' as absent.
                    ("", "$direct", None),
                ]
            ):
                distinct_id = f"user_{index}"
                _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
                properties = {
                    "$session_id": str(uuid7("2024-01-01")),
                    "$current_url": f"https://example.com{pathname}",
                    "$pathname": pathname,
                    "$referring_domain": referring_domain,
                    **self.STANDARD_EVENT_PROPERTIES,
                }
                if utm_source:
                    properties["utm_source"] = utm_source
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp="2024-01-01T09:00:00Z",
                    properties=properties,
                )

        flush_persons_and_events()

        select_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[self.team.pk],
            table_name="web_pre_aggregated_stats",
            granularity="hourly",
            select_only=True,
        )
        sync_execute(f"INSERT INTO web_pre_aggregated_stats\n{select_sql}")

    def _calculate(
        self,
        use_preagg: bool,
        custom_rules: list[CustomChannelRule],
        breakdown_by: WebStatsBreakdown = WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
        properties: list[SessionPropertyFilter] | None = None,
    ):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=properties or [],
            breakdownBy=breakdown_by,
            limit=100,
        )
        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=use_preagg,
            customChannelTypeRules=custom_rules,
        )
        return WebStatsTableQueryRunner(query=query, team=self.team, modifiers=modifiers).calculate()

    @parameterized.expand(
        [
            ("utm_source", CustomChannelField.UTM_SOURCE, "MyPartner", "Partner program", CustomChannelOperator.EXACT),
            ("pathname", CustomChannelField.PATHNAME, "/blog", "Blog", CustomChannelOperator.EXACT),
            (
                "referring_domain",
                CustomChannelField.REFERRING_DOMAIN,
                "google.com",
                "Search partner",
                CustomChannelOperator.EXACT,
            ),
            # Both paths null a stored 'null', so an is_set rule must skip that row on each of them.
            (
                "utm_source_is_set",
                CustomChannelField.UTM_SOURCE,
                None,
                "Campaign traffic",
                CustomChannelOperator.IS_SET,
            ),
            # A bare-domain entry URL has an empty pathname but is still set, on both paths.
            (
                "pathname_is_set",
                CustomChannelField.PATHNAME,
                None,
                "Landed somewhere",
                CustomChannelOperator.IS_SET,
            ),
        ]
    )
    def test_custom_rule_on_pre_aggregated_field(self, _name, key, value, channel_type, op):
        custom_rules = [_rule(channel_type, key, value, op)]

        preagg_response = self._calculate(use_preagg=True, custom_rules=custom_rules)
        live_response = self._calculate(use_preagg=False, custom_rules=custom_rules)

        assert preagg_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.PRE_AGGREGATED
        assert live_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LIVE

        assert channel_type in {result[0] for result in preagg_response.results}
        assert self._sort_results(preagg_response.results) == self._sort_results(live_response.results)

    @parameterized.expand(FIELDS_ABSENT_FROM_PRE_AGGREGATED)
    def test_custom_rule_on_absent_field_falls_back_to_live_query(self, _name, key, value, channel_type):
        custom_rules = [_rule(channel_type, key, value)]

        response = self._calculate(use_preagg=True, custom_rules=custom_rules)

        assert response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LIVE
        assert channel_type in {result[0] for result in response.results}

    @parameterized.expand(FIELDS_ABSENT_FROM_PRE_AGGREGATED)
    def test_channel_type_filter_with_custom_rule_on_absent_field_falls_back_to_live_query(
        self, _name, key, value, channel_type
    ):
        custom_rules = [_rule(channel_type, key, value)]

        response = self._calculate(
            use_preagg=True,
            custom_rules=custom_rules,
            breakdown_by=WebStatsBreakdown.BROWSER,
            properties=[
                SessionPropertyFilter(key="$channel_type", value=channel_type, operator="exact", type="session")
            ],
        )

        assert response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LIVE
        assert len(response.results) == 1
