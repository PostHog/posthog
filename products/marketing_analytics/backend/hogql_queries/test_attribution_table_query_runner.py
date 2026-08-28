import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    AttributionMode,
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    DateRange,
    EventPropertyFilter,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionQuery,
    PropertyMathType,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import PropertyDefinition
from posthog.models.team.team_marketing_analytics_config import MAX_ATTRIBUTION_WINDOW_DAYS
from posthog.models.utils import uuid7
from posthog.test.persons import create_person

from products.actions.backend.models.action import Action
from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
)

GOAL_ID = "goal-1"
CONVERSION_EVENT = "purchase"

# A 4-day window makes the half-life exactly 1 day (window // 4), so touchpoints one, two and three
# days before the conversion decay to 0.5, 0.25 and 0.125 — a geometric series whose normalized
# weights are the clean 4/7, 2/7, 1/7 asserted below.
WINDOW_DAYS = 4
CONVERSION_AT = "2023-01-10T12:00:00Z"
ONE_DAY_BEFORE = "2023-01-09T12:00:00Z"
TWO_DAYS_BEFORE = "2023-01-08T12:00:00Z"
THREE_DAYS_BEFORE = "2023-01-07T12:00:00Z"


class TestMarketingAnalyticsAttributionQueryRunner(ClickhouseTestMixin, BaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self._configure_goal()

    def _configure_goal(
        self,
        *,
        counts_as_revenue: bool = True,
        math: PropertyMathType | BaseMathType = PropertyMathType.SUM,
        math_property: str | None = "revenue",
    ) -> None:
        config = self.team.marketing_analytics_config
        config.attribution_window_days = WINDOW_DAYS
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event=CONVERSION_EVENT,
                name="Purchases",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Purchases",
                schema_map={},
                math=math,
                math_property=math_property,
                counts_as_revenue=counts_as_revenue,
            ).model_dump()
        ]
        config.save()

    def _session(
        self,
        distinct_id: str,
        started_at: str,
        *,
        utm_campaign: str | None = None,
        utm_source: str | None = None,
        utm_medium: str | None = None,
        referring_domain: str | None = "$direct",
        pageviews: int = 1,
    ) -> None:
        """One session's worth of pageviews. uuid7 seeds the session id so `$start_timestamp` lands on
        `started_at`, which is what the attribution window filters against. `$referring_domain` defaults
        to the `$direct` sentinel the SDKs send when there's no referrer — without it `$channel_type`
        classifies as Unknown rather than Direct."""
        session_id = str(uuid7(started_at))
        for _ in range(pageviews):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=started_at,
                properties={
                    "$session_id": session_id,
                    "$current_url": "https://example.com/",
                    "$pathname": "/",
                    **({"$referring_domain": referring_domain} if referring_domain is not None else {}),
                    **({"utm_campaign": utm_campaign} if utm_campaign else {}),
                    **({"utm_source": utm_source} if utm_source else {}),
                    **({"utm_medium": utm_medium} if utm_medium else {}),
                },
            )

    def _conversion(self, distinct_id: str, at: str, revenue: float = 100.0) -> None:
        _create_event(
            team=self.team,
            event=CONVERSION_EVENT,
            distinct_id=distinct_id,
            timestamp=at,
            properties={"revenue": revenue},
        )

    def _run(
        self,
        breakdown: MarketingAnalyticsAttributionBreakdown,
        *,
        exclude_direct: bool = False,
        exclude_unattributed: bool = False,
        date_from: str = "2023-01-01",
        date_to: str = "2023-01-31",
        lookback_days: int | None = None,
        allow_multiple_conversions: bool | None = None,
    ):
        flush_persons_and_events()
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            breakdownBy=breakdown,
            conversionGoalId=GOAL_ID,
            excludeDirectTraffic=exclude_direct,
            excludeUnattributed=exclude_unattributed,
            lookbackWindowDays=lookback_days,
            allowMultipleConversionsPerVisitor=allow_multiple_conversions,
            properties=[],
        )
        return MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team).calculate()

    @staticmethod
    def _by_breakdown(response) -> dict[str, dict[AttributionMode, float]]:
        """{breakdown value: {model: conversions}} — the shape every weight assertion needs."""
        return {row.breakdownValue: {cell.model: cell.conversions for cell in row.models} for row in response.results}

    def test_visitors_include_lookback_arrivals_that_can_earn_credit(self):
        # Credit looks back attribution_window_days before the date range, so reach must too: a visitor
        # whose only touch predates the range used to be missing from the denominator, which reported
        # conversion rates above 100%.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", "2022-12-30T12:00:00Z", utm_campaign="holiday")
        self._conversion("p1", "2023-01-02T12:00:00Z")

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)

        row = next(r for r in response.results if r.breakdownValue == "holiday")
        self.assertEqual(row.visitors, 1)
        self.assertEqual(row.influencedConversions, 1)
        self.assertEqual(row.models[0].conversionRate, 1.0)

    def test_unique_users_math_counts_each_person_once(self):
        # A dau goal on a frequent event ($pageview being the common case) must not count every matching
        # event as its own conversion: that reported more conversions than visitors. The person's three
        # conversion events collapse to their first, so each model splits exactly 1 conversion.
        self._configure_goal(counts_as_revenue=False, math=BaseMathType.DAU, math_property=None)
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", THREE_DAYS_BEFORE, utm_campaign="early")
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="late")
        self._conversion("p1", CONVERSION_AT)
        self._conversion("p1", "2023-01-10T13:00:00Z")
        self._conversion("p1", "2023-01-11T12:00:00Z")

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)

        self.assertEqual(response.totalConversions, 1)
        for row in response.results:
            self.assertEqual(row.influencedConversions, 1)
        by_campaign = self._by_breakdown(response)
        self.assertAlmostEqual(by_campaign["early"][AttributionMode.FIRST_TOUCH], 1.0, places=4)
        self.assertAlmostEqual(by_campaign["late"][AttributionMode.LAST_TOUCH], 1.0, places=4)

    @parameterized.expand(
        [
            # (goal math, toggle, expected conversions credited)
            ("count_default_counts_every_conversion", PropertyMathType.SUM, None, 3.0),
            ("count_toggled_off_counts_one", PropertyMathType.SUM, False, 1.0),
            ("unique_users_default_counts_one", BaseMathType.DAU, None, 1.0),
            ("unique_users_toggled_on_counts_every_conversion", BaseMathType.DAU, True, 3.0),
        ]
    )
    def test_multiple_conversions_toggle_overrides_goal_math(
        self, _name: str, math: PropertyMathType | BaseMathType, allow_multiple: bool | None, expected: float
    ):
        # Unset must follow the goal's math, and an explicit value must win over it in both directions.
        # Getting this backwards is invisible on a count goal (which already counts everything) and would
        # only show up on unique-users goals, where it would contradict the number the Dashboard reports.
        is_revenue = math == PropertyMathType.SUM
        self._configure_goal(counts_as_revenue=is_revenue, math=math, math_property="revenue" if is_revenue else None)
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="c")
        for at in (CONVERSION_AT, "2023-01-10T13:00:00Z", "2023-01-10T14:00:00Z"):
            self._conversion("p1", at)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, allow_multiple_conversions=allow_multiple)

        self.assertEqual(response.allowsMultipleConversionsPerVisitor, expected > 1.0)
        self.assertAlmostEqual(self._by_breakdown(response)["c"][AttributionMode.LAST_TOUCH], expected, places=4)
        self.assertEqual(response.results[0].influencedConversions, int(expected))

    def test_sessions_missing_from_the_sessions_table_are_not_touchpoints(self):
        # A session id that resolves to no session row comes back as epoch zero, not null, because the join
        # fills a non-nullable column with its default. Testing for null instead of for a real timestamp let
        # 1970 touchpoints into the array, where they sorted to the front, consumed truncation slots, and
        # earned nothing — so conversions whose own session was one of these silently went uncredited.
        create_person(team=self.team, distinct_ids=["p1"])
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp=ONE_DAY_BEFORE,
            properties={
                "$session_id": "00000000-0000-0000-0000-000000000000",
                "$pathname": "/",
                "$referring_domain": "$direct",
                "utm_campaign": "unresolvable",
            },
        )
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="real")
        self._conversion("p1", CONVERSION_AT)

        by_campaign = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertNotIn("unresolvable", by_campaign)
        self.assertAlmostEqual(by_campaign["real"][AttributionMode.LINEAR], 1.0, places=4)

    def test_conversions_before_the_date_range_are_not_credited(self):
        # Touchpoint collection reaches a lookback window further back than the date range, and the
        # conversion side used to ride on that same widened scan: conversions from the older stretch were
        # credited and counted, so the table silently reported a much longer period than the one asked for.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", "2022-12-20T12:00:00Z", utm_campaign="c")
        self._conversion("p1", "2022-12-21T12:00:00Z", revenue=500.0)  # before date_from
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="c")
        self._conversion("p1", CONVERSION_AT, revenue=100.0)  # inside the range

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, date_from="2023-01-01")

        self.assertEqual(response.totalConversions, 1)
        row = response.results[0]
        self.assertEqual(row.influencedConversions, 1)
        self.assertAlmostEqual(row.influencedValue or 0.0, 100.0, places=2)

    def test_conversions_in_the_same_second_stay_separate(self):
        # Conversions were keyed by (dimension, person, timestamp) with the timestamp truncated to whole
        # seconds, so a retry or a batched server-side send merged two conversions into one: the influenced
        # count under-reported and one conversion's revenue silently vanished, while the model columns
        # still counted both. The row contradicted itself.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="c")
        self._conversion("p1", CONVERSION_AT, revenue=100.0)
        self._conversion("p1", CONVERSION_AT, revenue=100.0)

        row = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN).results[0]

        self.assertEqual(row.influencedConversions, 2)
        self.assertAlmostEqual(row.influencedValue or 0.0, 200.0, places=2)
        last_touch = next(c for c in row.models if c.model == AttributionMode.LAST_TOUCH)
        self.assertAlmostEqual(last_touch.conversions, 2.0, places=4)
        self.assertAlmostEqual(last_touch.conversionValue or 0.0, 200.0, places=2)

    def test_every_model_splits_one_conversion_its_own_way(self):
        # The one test that catches this design's central risk: five weight arrays are built per
        # conversion and exploded through a single shared ARRAY JOIN, so indexing the wrong array into a
        # model's column, or an off-by-one in `arrayEnumerate(ts)`, silently reports another model's
        # numbers. Also pins time decay's normalization and position-based's 40/20/40.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", THREE_DAYS_BEFORE, utm_campaign="early")
        self._session("p1", TWO_DAYS_BEFORE, utm_campaign="middle")
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="late")
        self._conversion("p1", CONVERSION_AT, revenue=100.0)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)
        by_campaign = self._by_breakdown(response)

        self.assertEqual(set(by_campaign), {"early", "middle", "late"})

        self.assertAlmostEqual(by_campaign["early"][AttributionMode.FIRST_TOUCH], 1.0, places=4)
        self.assertAlmostEqual(by_campaign["middle"][AttributionMode.FIRST_TOUCH], 0.0, places=4)
        self.assertAlmostEqual(by_campaign["late"][AttributionMode.FIRST_TOUCH], 0.0, places=4)

        self.assertAlmostEqual(by_campaign["early"][AttributionMode.LAST_TOUCH], 0.0, places=4)
        self.assertAlmostEqual(by_campaign["late"][AttributionMode.LAST_TOUCH], 1.0, places=4)

        for campaign in ("early", "middle", "late"):
            self.assertAlmostEqual(by_campaign[campaign][AttributionMode.LINEAR], 1 / 3, places=4)

        # exp(-ln2 * days) normalized over 0.5 + 0.25 + 0.125
        self.assertAlmostEqual(by_campaign["late"][AttributionMode.TIME_DECAY], 4 / 7, places=4)
        self.assertAlmostEqual(by_campaign["middle"][AttributionMode.TIME_DECAY], 2 / 7, places=4)
        self.assertAlmostEqual(by_campaign["early"][AttributionMode.TIME_DECAY], 1 / 7, places=4)

        self.assertAlmostEqual(by_campaign["early"][AttributionMode.POSITION_BASED], 0.4, places=4)
        self.assertAlmostEqual(by_campaign["middle"][AttributionMode.POSITION_BASED], 0.2, places=4)
        self.assertAlmostEqual(by_campaign["late"][AttributionMode.POSITION_BASED], 0.4, places=4)

    def test_every_model_conserves_total_credit(self):
        # Weights must sum to 1 per conversion, so each model's column sums to the conversion count no
        # matter how many touchpoints there were. A normalization bug (or a dropped touchpoint) shows up
        # here as a column that quietly totals less than the truth.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", THREE_DAYS_BEFORE, utm_campaign="a")
        self._session("p1", TWO_DAYS_BEFORE, utm_campaign="b")
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="c")
        self._conversion("p1", CONVERSION_AT)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)

        for model in response.models:
            total = sum(cell.conversions for row in response.results for cell in row.models if cell.model == model)
            self.assertAlmostEqual(total, 1.0, places=4, msg=f"{model} did not conserve credit")

    def test_influenced_counts_each_conversion_once_and_overlaps_across_rows(self):
        # Guards the per-(dimension, person, conversion) collapse. Without it "influenced" would count
        # touchpoint rows instead of conversions. The deliberate over-count across rows is asserted too,
        # so a later "fix" that dedupes it away fails here rather than silently changing the meaning.
        create_person(team=self.team, distinct_ids=["p1"])
        for conversion_at, first_touch, second_touch in [
            (CONVERSION_AT, THREE_DAYS_BEFORE, TWO_DAYS_BEFORE),
            ("2023-01-11T12:00:00Z", "2023-01-08T18:00:00Z", "2023-01-09T18:00:00Z"),
        ]:
            self._session("p1", first_touch, utm_campaign="a")
            self._session("p1", second_touch, utm_campaign="b")
            self._conversion("p1", conversion_at)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)
        influenced = {row.breakdownValue: row.influencedConversions for row in response.results}

        self.assertEqual(influenced["a"], 2)
        self.assertEqual(influenced["b"], 2)
        # Both campaigns influenced both conversions, so the column intentionally exceeds the real total.
        self.assertEqual(sum(influenced.values()), 4)
        self.assertEqual(response.totalConversions, 2)

    def test_direct_traffic_earns_credit(self):
        # The Dashboard's touchpoint filter requires utm_campaign AND utm_source, which drops Direct,
        # Organic search and Referral entirely. This runner defines a touchpoint as a session instead,
        # and this test fails the moment someone "reuses" that filter here.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE)  # no utm, no referrer -> Direct
        self._conversion("p1", CONVERSION_AT)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CHANNEL)
        by_channel = self._by_breakdown(response)

        self.assertIn("Direct", by_channel)
        self.assertAlmostEqual(by_channel["Direct"][AttributionMode.LAST_TOUCH], 1.0, places=4)

    def test_excluding_direct_redistributes_its_credit_instead_of_losing_it(self):
        # The exclusion has to happen before the weights are computed. Applied afterwards, direct's share
        # would simply vanish and the remaining columns would stop summing to the conversion count.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google", utm_medium="cpc")
        self._session("p1", ONE_DAY_BEFORE)  # Direct
        self._conversion("p1", CONVERSION_AT)

        with_direct = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CHANNEL))
        self.assertIn("Direct", with_direct)
        paid_channel = next(channel for channel in with_direct if channel != "Direct")
        self.assertAlmostEqual(with_direct[paid_channel][AttributionMode.LINEAR], 0.5, places=4)

        without_direct = self._by_breakdown(
            self._run(MarketingAnalyticsAttributionBreakdown.CHANNEL, exclude_direct=True)
        )
        self.assertNotIn("Direct", without_direct)
        self.assertAlmostEqual(without_direct[paid_channel][AttributionMode.LINEAR], 1.0, places=4)

    def test_excluding_unattributed_redistributes_the_none_rows_credit(self):
        # Same before-the-weights placement as the direct exclusion, judged on the breakdown's raw
        # session field: a session with no utm_campaign renders as the "(none)" row, and excluding it
        # hands its share to the campaigns that were actually tagged.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_campaign="summer")
        self._session("p1", ONE_DAY_BEFORE)  # no utm_campaign -> the "(none)" row
        self._conversion("p1", CONVERSION_AT)

        with_none = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))
        self.assertIn("", with_none)
        self.assertAlmostEqual(with_none["summer"][AttributionMode.LINEAR], 0.5, places=4)

        without_none = self._by_breakdown(
            self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, exclude_unattributed=True)
        )
        self.assertNotIn("", without_none)
        self.assertAlmostEqual(without_none["summer"][AttributionMode.LINEAR], 1.0, places=4)

    def test_excluding_unattributed_drops_unknown_channels(self):
        # Channel is special-cased: the classifier's raw value can literally be "Unknown" (a session with
        # no referrer sentinel at all), which must be treated as unattributed alongside empty values.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google", utm_medium="cpc")
        self._session("p1", ONE_DAY_BEFORE, referring_domain=None)  # unclassifiable -> Unknown
        self._conversion("p1", CONVERSION_AT)

        with_unknown = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CHANNEL))
        self.assertIn("Unknown", with_unknown)
        paid_channel = next(channel for channel in with_unknown if channel != "Unknown")
        self.assertAlmostEqual(with_unknown[paid_channel][AttributionMode.LINEAR], 0.5, places=4)

        without_unknown = self._by_breakdown(
            self._run(MarketingAnalyticsAttributionBreakdown.CHANNEL, exclude_unattributed=True)
        )
        self.assertNotIn("Unknown", without_unknown)
        self.assertAlmostEqual(without_unknown[paid_channel][AttributionMode.LINEAR], 1.0, places=4)

    def test_campaign_name_mappings_collapse_dirty_utm_spellings(self):
        # The team's own mapping says these two spellings are one campaign, and the Dashboard reports
        # them as one. Left unmapped here, each spelling is its own row and the models credit them
        # independently — first touch names one spelling, last touch the other — so the model comparison
        # this table exists for would read as a difference between campaigns that are the same campaign.
        config = self.team.marketing_analytics_config
        config.campaign_name_mappings = {"GoogleAds": {"Spring Sale 2026": ["spring_sale_2026", "spring-sale-2026"]}}
        config.save()

        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google", utm_campaign="spring_sale_2026")
        self._session("p1", ONE_DAY_BEFORE, utm_source="google", utm_campaign="spring-sale-2026")
        self._conversion("p1", CONVERSION_AT)

        rows = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertEqual(list(rows), ["Spring Sale 2026"])
        # One campaign touched twice holds the whole conversion under every model.
        for model in [AttributionMode.FIRST_TOUCH, AttributionMode.LAST_TOUCH, AttributionMode.LINEAR]:
            self.assertAlmostEqual(rows["Spring Sale 2026"][model], 1.0, places=4)

    def test_campaign_name_mappings_are_scoped_to_the_mapped_integration(self):
        # The mapping keys off the touchpoint's source, so the same spelling arriving on a source that
        # doesn't belong to the mapped integration must stay as it came.
        config = self.team.marketing_analytics_config
        config.campaign_name_mappings = {"GoogleAds": {"Spring Sale 2026": ["spring_sale_2026"]}}
        config.save()

        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google", utm_campaign="spring_sale_2026")
        self._session("p1", ONE_DAY_BEFORE, utm_source="newsletter", utm_campaign="spring_sale_2026")
        self._conversion("p1", CONVERSION_AT)

        rows = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertEqual(sorted(rows), ["Spring Sale 2026", "spring_sale_2026"])

    def test_campaign_id_matching_preference_leaves_the_displayed_campaign_raw(self):
        # With match_field=campaign_id the mapping's clean_name is an *id*, which the Dashboard uses to
        # find the cost row while leaving the displayed campaign name untouched. There is no cost join
        # here, so applying it would put a bare id in the campaign column.
        config = self.team.marketing_analytics_config
        config.campaign_name_mappings = {"GoogleAds": {"10042": ["spring_sale_2026"]}}
        config.campaign_field_preferences = {"GoogleAds": {"match_field": "campaign_id"}}
        config.save()

        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_source="google", utm_campaign="spring_sale_2026")
        self._conversion("p1", CONVERSION_AT)

        rows = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertEqual(list(rows), ["spring_sale_2026"])

    def test_an_empty_campaign_is_never_mapped_onto_a_real_name(self):
        # Nothing stops a team listing "" among a campaign's raw values, but an empty utm_campaign is the
        # absence of a campaign rather than a misspelling of one. Mapping it would invent attribution and
        # would leave "Exclude unattributed traffic" dropping a row labelled like a campaign that stayed.
        config = self.team.marketing_analytics_config
        config.campaign_name_mappings = {"GoogleAds": {"Spring Sale 2026": ["", "spring_sale_2026"]}}
        config.save()

        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google", utm_campaign="spring_sale_2026")
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")  # no utm_campaign
        self._conversion("p1", CONVERSION_AT)

        rows = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))
        self.assertEqual(sorted(rows), ["", "Spring Sale 2026"])

        # ...and it stays the row the exclusion drops.
        excluded = self._by_breakdown(
            self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, exclude_unattributed=True)
        )
        self.assertEqual(list(excluded), ["Spring Sale 2026"])

    def test_excluding_unattributed_drops_the_organic_source_row(self):
        # Source is the breakdown where "unattributed" is easiest to get wrong: an empty utm_source is
        # *displayed* as "organic", a real-looking name, so it renders nothing like the "(none)" row the
        # other UTM breakdowns produce. It is still the absence of a source, so it goes — and the credit
        # it held renormalizes onto the sources that were actually tagged.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google")
        self._session("p1", ONE_DAY_BEFORE)  # no utm_source -> displayed as "organic"
        self._conversion("p1", CONVERSION_AT)

        with_organic = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.SOURCE))
        self.assertIn("organic", with_organic)
        self.assertAlmostEqual(with_organic["google"][AttributionMode.LINEAR], 0.5, places=4)

        without_organic = self._by_breakdown(
            self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, exclude_unattributed=True)
        )
        self.assertNotIn("organic", without_organic)
        self.assertAlmostEqual(without_organic["google"][AttributionMode.LINEAR], 1.0, places=4)

    def test_excluding_unattributed_drops_the_direct_referring_domain_sentinel(self):
        # `$entry_referring_domain` holds the "$direct" sentinel rather than an empty value when a session
        # arrived with no referrer, so an emptiness test alone would leave a raw sentinel in the results
        # as if it were a real referrer.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, referring_domain="google.com")
        self._session("p1", ONE_DAY_BEFORE)  # defaults to the "$direct" sentinel
        self._conversion("p1", CONVERSION_AT)

        with_direct = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN))
        self.assertIn("$direct", with_direct)
        self.assertAlmostEqual(with_direct["google.com"][AttributionMode.LINEAR], 0.5, places=4)

        without_direct = self._by_breakdown(
            self._run(MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN, exclude_unattributed=True)
        )
        self.assertNotIn("$direct", without_direct)
        self.assertAlmostEqual(without_direct["google.com"][AttributionMode.LINEAR], 1.0, places=4)

    def test_repeat_touches_on_one_dimension_sum_their_weight(self):
        # A dimension touched on three of four sessions should hold 0.75 of the linear credit as one row,
        # not appear three times at 0.25. Guards the weight roll-up in the same collapse as the influenced
        # count — a change from sum() to any() there would pass every other test in this file.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", THREE_DAYS_BEFORE, utm_campaign="repeat")
        self._session("p1", TWO_DAYS_BEFORE, utm_campaign="repeat")
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="repeat")
        self._session("p1", "2023-01-09T18:00:00Z", utm_campaign="once")
        self._conversion("p1", CONVERSION_AT)

        by_campaign = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertAlmostEqual(by_campaign["repeat"][AttributionMode.LINEAR], 0.75, places=4)
        self.assertAlmostEqual(by_campaign["once"][AttributionMode.LINEAR], 0.25, places=4)

    def test_repeated_pageviews_in_one_session_count_as_a_single_touchpoint(self):
        # Touchpoint grain is the session, not the pageview. If it regressed to per-pageview, a visitor
        # who browses several pages with the query string still attached would inflate that campaign's
        # share — here 'browsed' would take 3/4 of the linear credit instead of half.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_campaign="browsed", pageviews=3)
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="bounced", pageviews=1)
        self._conversion("p1", CONVERSION_AT)

        by_campaign = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertAlmostEqual(by_campaign["browsed"][AttributionMode.LINEAR], 0.5, places=4)
        self.assertAlmostEqual(by_campaign["bounced"][AttributionMode.LINEAR], 0.5, places=4)

    def test_touchpoints_outside_the_attribution_window_earn_nothing(self):
        # The window is the whole point of an attribution model; a dropped bound would credit a touch
        # from any point in history.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", "2022-12-01T12:00:00Z", utm_campaign="ancient")
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="recent")
        self._conversion("p1", CONVERSION_AT)

        by_campaign = self._by_breakdown(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertAlmostEqual(by_campaign["recent"][AttributionMode.LINEAR], 1.0, places=4)
        self.assertNotIn("ancient", by_campaign)

    def test_lookback_override_shrinks_the_window(self):
        # The query-level override must actually reach the window math; a dropped wire silently falls
        # back to the team's configured window and the UI control does nothing.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", THREE_DAYS_BEFORE, utm_campaign="early")
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="late")
        self._conversion("p1", CONVERSION_AT)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, lookback_days=2)

        self.assertEqual(response.attributionWindowDays, 2)
        by_campaign = self._by_breakdown(response)
        self.assertAlmostEqual(by_campaign["late"][AttributionMode.LINEAR], 1.0, places=4)
        # The early touch stays visible as reach, but a 2-day window must not credit a 3-day-old touch.
        self.assertAlmostEqual(by_campaign["early"][AttributionMode.LINEAR], 0.0, places=4)

    def test_conversions_with_no_touchpoints_are_reported_not_dropped(self):
        # An ARRAY JOIN over an empty touchpoint array yields no rows, so these conversions leave the
        # table entirely. Reporting them is the only way a user can reconcile the model columns against
        # their real conversion count.
        create_person(team=self.team, distinct_ids=["p1"])
        create_person(team=self.team, distinct_ids=["p2"])
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="a")
        self._conversion("p1", CONVERSION_AT)
        self._conversion("p2", CONVERSION_AT)  # never browsed

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)

        self.assertEqual(response.totalConversions, 2)
        self.assertEqual(response.unattributedConversions, 1)

    def test_value_columns_are_populated_only_for_revenue_goals(self):
        # `hasValue` gates the value columns in the table. If the flag and the numbers disagree the UI
        # either hides real revenue or shows a column of nulls.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="a")
        self._conversion("p1", CONVERSION_AT, revenue=250.0)

        revenue_response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)
        self.assertTrue(revenue_response.hasValue)
        self.assertAlmostEqual(revenue_response.results[0].influencedValue or 0.0, 250.0, places=2)
        last_touch = next(c for c in revenue_response.results[0].models if c.model == AttributionMode.LAST_TOUCH)
        self.assertAlmostEqual(last_touch.conversionValue or 0.0, 250.0, places=2)

        self._configure_goal(counts_as_revenue=False)
        countable_response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)
        self.assertFalse(countable_response.hasValue)
        self.assertIsNone(countable_response.results[0].influencedValue)
        self.assertIsNone(countable_response.results[0].models[0].conversionValue)

    def test_touchpoint_scan_is_restricted_to_people_who_converted(self):
        # Widening touchpoints from UTM-tagged pageviews to every session multiplies the pageview side by
        # roughly 10x; the converter semi-join is what pays that back. Dropping it changes no result and
        # costs one to two orders of magnitude more, so no behavioural test can see it.
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            breakdownBy=MarketingAnalyticsAttributionBreakdown.CHANNEL,
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team)
        ctes = runner.to_query().ctes or {}
        person_arrays = ctes["person_arrays"].expr
        assert isinstance(person_arrays, ast.SelectQuery)

        class FindSubqueryIn(TraversingVisitor):
            def __init__(self) -> None:
                self.found = False

            def visit_compare_operation(self, node: ast.CompareOperation) -> None:
                if node.op == ast.CompareOperationOp.In and isinstance(node.right, ast.SelectQuery):
                    self.found = True
                super().visit_compare_operation(node)

        finder = FindSubqueryIn()
        finder.visit(person_arrays.where)
        self.assertTrue(finder.found, "person_arrays must restrict the events scan to converting persons")

    def test_action_goals_credit_the_events_the_action_matches(self):
        # The action branch resolves the goal through Postgres and `action_to_expr` rather than a plain
        # event name. A goal that silently matched nothing would render an empty table that reads as an
        # honest absence of conversions.
        action = Action.objects.create(team=self.team, name="Purchased", steps_json=[{"event": CONVERSION_EVENT}])
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter2(
                kind="ActionsNode",
                id=str(action.pk),
                name="Purchased",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Purchased",
                schema_map={},
                math=BaseMathType.TOTAL,
            ).model_dump()
        ]
        config.save()
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="a")
        self._conversion("p1", CONVERSION_AT)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)

        self.assertEqual(response.totalConversions, 1)
        by_campaign = self._by_breakdown(response)
        self.assertAlmostEqual(by_campaign["a"][AttributionMode.LAST_TOUCH], 1.0, places=4)

    def test_referring_domain_breakdown_reads_the_sessions_entry_field(self):
        # Channel and source get sentinel and normalization treatment; the remaining breakdowns pass the
        # session's entry field straight through. A wrong field mapping would silently bucket every row
        # under one value.
        create_person(team=self.team, distinct_ids=["p1"])
        create_person(team=self.team, distinct_ids=["p2"])
        self._session("p1", ONE_DAY_BEFORE, referring_domain="google.com")
        self._conversion("p1", CONVERSION_AT)
        self._session("p2", ONE_DAY_BEFORE, referring_domain="news.ycombinator.com")
        self._conversion("p2", CONVERSION_AT)

        response = self._run(MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN)

        by_domain = self._by_breakdown(response)
        self.assertAlmostEqual(by_domain["google.com"][AttributionMode.LAST_TOUCH], 1.0, places=4)
        self.assertAlmostEqual(by_domain["news.ycombinator.com"][AttributionMode.LAST_TOUCH], 1.0, places=4)

    def test_another_goals_problem_does_not_break_the_selected_goal(self):
        # An unusable goal elsewhere in the team's settings used to replace the whole result with its
        # warning, because those warnings were returned as the response's `error` and the table renders
        # any error instead of rows. Asking for the broken goal itself still has to say why.
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            *config.conversion_goals,
            ConversionGoalFilter1(
                kind="EventsNode",
                event="",
                name="All events",
                conversion_goal_id="broken-goal",
                conversion_goal_name="All events (misconfigured)",
                schema_map={},
                math=BaseMathType.TOTAL,
            ).model_dump(),
        ]
        config.save()
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="a")
        self._conversion("p1", CONVERSION_AT)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)
        self.assertIsNone(response.error)
        self.assertEqual([row.breakdownValue for row in response.results], ["a"])

        broken = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId="broken-goal",
            properties=[],
        )
        with self.assertRaises(ValueError) as raised:
            MarketingAnalyticsAttributionQueryRunner(query=broken, team=self.team).to_query()
        self.assertIn("All events (misconfigured)", str(raised.exception))

    @parameterized.expand(
        [
            ("unknown_goal", "does-not-exist"),
            ("empty_goal", ""),
        ]
    )
    def test_unresolvable_goal_raises(self, _name: str, goal_id: str):
        # A goal id that doesn't resolve must fail loudly. Falling through to "no conversions" would
        # render an empty table that looks like a genuine absence of conversions.
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId=goal_id,
            properties=[],
        )
        runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team)
        with self.assertRaises(ValueError):
            runner.to_query()

    def test_goal_property_filters_narrow_the_conversions_counted(self):
        # The goal's own property filters are part of what a conversion is. Matching on the event name
        # alone counts purchases the Dashboard excludes, so the same goal reports two different numbers
        # on two tabs with nothing saying which is right.
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event=CONVERSION_EVENT,
                name="Big purchases",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Big purchases",
                schema_map={},
                math=BaseMathType.TOTAL,
                properties=[
                    EventPropertyFilter(key="plan", operator=PropertyOperator.EXACT, value=["pro"], type="event")
                ],
            ).model_dump()
        ]
        config.save()
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_campaign="a")
        for at, plan in ((CONVERSION_AT, "pro"), ("2023-01-10T13:00:00Z", "free")):
            _create_event(
                team=self.team,
                event=CONVERSION_EVENT,
                distinct_id="p1",
                timestamp=at,
                properties={"revenue": 100.0, "plan": plan},
            )

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)

        self.assertEqual(response.totalConversions, 1)
        by_campaign = self._by_breakdown(response)
        self.assertAlmostEqual(by_campaign["a"][AttributionMode.LAST_TOUCH], 1.0, places=4)

    def test_action_goal_whose_action_is_gone_reports_the_misconfiguration(self):
        # An unresolvable action used to raise Action.DoesNotExist out of query building, so a goal
        # pointing at a deleted action 500d instead of telling the user to fix the goal.
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter2(
                kind="ActionsNode",
                id=99999999,
                name="Purchased",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Purchased",
                schema_map={},
                math=BaseMathType.TOTAL,
            ).model_dump()
        ]
        config.save()

        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        with self.assertRaises(ValueError) as raised:
            MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team).to_query()
        self.assertIn("no longer exists", str(raised.exception))

    def test_reconciliation_survives_a_result_with_no_dimension_rows(self):
        # Conversions with no session at all produce neither credit nor reach, so the join emits nothing.
        # The counts used to be scalar subqueries on that empty row set, reporting zero conversions
        # instead of "all of them went uncredited", which is the one thing worth saying here.
        create_person(team=self.team, distinct_ids=["p1"])
        self._conversion("p1", CONVERSION_AT)

        response = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN)

        self.assertEqual(response.results, [])
        self.assertEqual(response.totalConversions, 1)
        self.assertEqual(response.unattributedConversions, 1)

    def test_per_conversion_is_materialized_for_its_two_readers(self):
        # Two CTEs read per_conversion, and ClickHouse re-evaluates a plain CTE at each reference, which
        # would run the events scan underneath it twice. Nothing about the results can show this.
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        ctes = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team).to_query().ctes or {}
        self.assertTrue(ctes["per_conversion"].materialized)

    @parameterized.expand(
        [
            ("restricted_for_this_user", True),
            ("not_restricted", False),
        ]
    )
    def test_property_denied_to_this_user_is_never_read(self, _name: str, restricted: bool):
        # The runner hands execute_hogql_query a prebuilt context, which stops it building a user-aware
        # one, and the printer loads property-level access control off that context. A context without the
        # user resolves only the team's default restrictions, so a property denied to this user alone was
        # read unmasked. ConversionGoalProcessor skips precompute specifically to fall back on this
        # masking, so it has to hold on the direct path.
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event=CONVERSION_EVENT,
                name="Pro purchases",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Pro purchases",
                schema_map={},
                math=BaseMathType.TOTAL,
                properties=[
                    EventPropertyFilter(key="plan", operator=PropertyOperator.EXACT, value=["pro"], type="event")
                ],
            ).model_dump()
        ]
        config.save()

        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team, user=self.user)
        context = runner._shared_hogql_context
        # execute_hogql_query flips this on the context it is handed; do the same to print the real query.
        context.enable_select_queries = True

        # Mirrors the real lookup: userless callers get the team defaults only, which is why a context
        # missing the user silently loses this user's own denial.
        def restrictions_for(*, user, **_kwargs) -> set:
            if user is None or not restricted:
                return set()
            return {RestrictedProperty(name="plan", property_type=PropertyDefinition.Type.EVENT)}

        with patch(
            "products.access_control.backend.property_access_control.get_restricted_properties_with_group_type_index_for_team",
            side_effect=restrictions_for,
        ):
            prepare_and_print_ast(runner.to_query(), context=context, dialect="clickhouse")

        # The property only reaches ClickHouse as a parameter when the query actually extracts it.
        self.assertEqual("plan" in str(context.values), not restricted)

    @parameterized.expand([("zero", 0), ("negative", -1), ("over_the_ceiling", MAX_ATTRIBUTION_WINDOW_DAYS + 1)])
    def test_lookback_override_outside_the_allowed_range_is_rejected(self, _name: str, days: int):
        # The override widens the events scan and the schema types it as a plain integer, so without this
        # a hand-built query could scan the team's entire event history.
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId=GOAL_ID,
            lookbackWindowDays=days,
            properties=[],
        )
        with self.assertRaises(ValueError):
            MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team).to_query()

    def _printed_sql(self, breakdown: MarketingAnalyticsAttributionBreakdown) -> str:
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            breakdownBy=breakdown,
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team)
        context = runner._shared_hogql_context
        # execute_hogql_query flips this on the context it is handed; do the same to print the real query.
        context.enable_select_queries = True
        printed = prepare_and_print_ast(runner.to_query(), context=context, dialect="clickhouse")
        return pretty_print_in_tests(printed[0] if isinstance(printed, tuple) else printed, self.team.pk)

    # One breakdown per SQL shape. Campaign reads a stored property, and the five breakdowns not listed
    # here produce the same query with a different column. Source adds the alias normalization, and
    # channel runs the classifier over raw_sessions.
    @parameterized.expand(
        [
            ("campaign", MarketingAnalyticsAttributionBreakdown.CAMPAIGN),
            ("source", MarketingAnalyticsAttributionBreakdown.SOURCE),
            ("channel", MarketingAnalyticsAttributionBreakdown.CHANNEL),
        ]
    )
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_attribution_table_sql(self, _name: str, breakdown: MarketingAnalyticsAttributionBreakdown):
        assert self._printed_sql(breakdown) == self.snapshot
