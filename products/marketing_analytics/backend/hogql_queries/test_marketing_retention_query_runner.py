from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    DateRange,
    EventPropertyFilter,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsRetentionInterval,
    MarketingAnalyticsRetentionQuery,
    MarketingAnalyticsRetentionReturningEvent,
    MarketingAnalyticsRetentionStartEvent,
    PropertyOperator,
)

from posthog.hogql.constants import MAX_SELECT_RETENTION_LIMIT

from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL
from posthog.models.team import WeekStartDay
from posthog.models.utils import uuid7
from posthog.test.persons import create_person

from products.marketing_analytics.backend.hogql_queries.marketing_retention_query_runner import (
    MAX_BREAKDOWN_LIMIT,
    MAX_COHORTS,
    MAX_TOTAL_INTERVALS,
    MarketingAnalyticsRetentionQueryRunner,
)

GOAL_ID = "goal-1"
CONVERSION_EVENT = "purchase"
SIGNUP_GOAL_ID = "goal-2"
SIGNUP_EVENT = "signed_up"

# Every timestamp below is a Wednesday, so a cohort can't drift into the neighbouring week whichever
# day the team's week starts on.
WEEK_0 = "2023-01-04T12:00:00Z"
WEEK_1 = "2023-01-11T12:00:00Z"
WEEK_2 = "2023-01-18T12:00:00Z"
WEEK_3 = "2023-01-25T12:00:00Z"
BEFORE_RANGE = "2022-12-14T12:00:00Z"

DATE_FROM = "2023-01-02"
DATE_TO = "2023-01-29"


class TestMarketingAnalyticsRetentionQueryRunner(ClickhouseTestMixin, BaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event=CONVERSION_EVENT,
                name="Purchases",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Purchases",
                schema_map={},
                math=BaseMathType.TOTAL,
                counts_as_revenue=False,
            ).model_dump(),
            ConversionGoalFilter1(
                kind="EventsNode",
                event=SIGNUP_EVENT,
                name="Sign ups",
                conversion_goal_id=SIGNUP_GOAL_ID,
                conversion_goal_name="Sign ups",
                schema_map={},
                math=BaseMathType.TOTAL,
                counts_as_revenue=False,
            ).model_dump(),
        ]
        config.save()

    def _session(
        self,
        distinct_id: str,
        started_at: str,
        *,
        utm_source: str | None = None,
        utm_campaign: str | None = None,
        referring_domain: str | None = "$direct",
        path: str = "/",
    ) -> None:
        """One session's pageview. uuid7 seeds the session id so `$start_timestamp` lands on `started_at`,
        which is what the acquisition window filters against. `$referring_domain` defaults to the
        `$direct` sentinel the SDKs send when there's no referrer — without it `$channel_type` classifies
        as Unknown rather than Direct."""
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=started_at,
            properties={
                "$session_id": str(uuid7(started_at)),
                "$current_url": f"https://example.com{path}",
                "$pathname": path,
                **({"$referring_domain": referring_domain} if referring_domain is not None else {}),
                **({"utm_source": utm_source} if utm_source else {}),
                **({"utm_campaign": utm_campaign} if utm_campaign else {}),
            },
        )

    def _conversion(self, distinct_id: str, at: str) -> None:
        _create_event(team=self.team, event=CONVERSION_EVENT, distinct_id=distinct_id, timestamp=at)

    def _signup(self, distinct_id: str, at: str) -> None:
        _create_event(team=self.team, event=SIGNUP_EVENT, distinct_id=distinct_id, timestamp=at)

    def _query(
        self,
        breakdown: MarketingAnalyticsAttributionBreakdown = MarketingAnalyticsAttributionBreakdown.SOURCE,
        *,
        date_from: str = DATE_FROM,
        date_to: str | None = DATE_TO,
        interval: MarketingAnalyticsRetentionInterval = MarketingAnalyticsRetentionInterval.WEEK,
        total_intervals: int = 4,
        returning_event: MarketingAnalyticsRetentionReturningEvent = MarketingAnalyticsRetentionReturningEvent.ACTIVITY,
        start_event: MarketingAnalyticsRetentionStartEvent = MarketingAnalyticsRetentionStartEvent.ARRIVAL,
        start_goal_id: str = GOAL_ID,
        only_new_users: bool = True,
        exclude_direct: bool = False,
        exclude_unattributed: bool = False,
        breakdown_limit: int | None = None,
        new_user_lookback_days: int | None = None,
        properties: list | None = None,
    ) -> MarketingAnalyticsRetentionQuery:
        return MarketingAnalyticsRetentionQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            breakdownBy=breakdown,
            retentionInterval=interval,
            totalIntervals=total_intervals,
            returningEvent=returning_event,
            conversionGoalId=GOAL_ID,
            startEvent=start_event,
            startConversionGoalId=start_goal_id,
            onlyNewUsers=only_new_users,
            excludeDirectTraffic=exclude_direct,
            excludeUnattributed=exclude_unattributed,
            breakdownLimit=breakdown_limit,
            newUserLookbackDays=new_user_lookback_days,
            properties=properties or [],
        )

    def _run(self, *args, **kwargs):
        flush_persons_and_events()
        return MarketingAnalyticsRetentionQueryRunner(query=self._query(*args, **kwargs), team=self.team).calculate()

    @staticmethod
    def _rows_by_value(response) -> dict[str, list]:
        rows: dict[str, list] = {}
        for row in response.results:
            rows.setdefault(row.breakdownValue, []).append(row)
        return rows

    def test_cohort_takes_the_first_sessions_source_not_the_last(self):
        # The whole point of acquisition cohorting: a person who arrives via google and later returns via
        # a bing link belongs to google. Reading the last session instead would credit every channel that
        # ever re-touched a user, which is what a plain breakdown on session properties does.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._session("p1", WEEK_1, utm_source="bing")

        response = self._run()

        rows = self._rows_by_value(response)
        self.assertEqual(list(rows), ["google"])
        self.assertEqual(rows["google"][0].cohortSize, 1)

    def test_person_acquired_in_week_one_is_absent_from_week_zero(self):
        # A cohort row must hold only the people who arrived in that period. Off-by-one here silently
        # merges every cohort into the first one and makes retention look perfect.
        create_person(team=self.team, distinct_ids=["p1"])
        create_person(team=self.team, distinct_ids=["p2"])
        self._session("p1", WEEK_0, utm_source="google")
        self._session("p2", WEEK_1, utm_source="google")

        response = self._run()

        by_index = {row.cohortIndex: row.cohortSize for row in response.results}
        self.assertEqual(by_index, {0: 1, 1: 1})

    def test_returning_in_a_later_period_fills_that_column(self):
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._session("p1", WEEK_2, utm_source="google")

        response = self._run()

        row = next(r for r in response.results if r.cohortIndex == 0)
        self.assertEqual([cell.count for cell in row.values], [1, 0, 1, 0])
        self.assertEqual(row.values[0].rate, 1.0)

    @parameterized.expand([("only_new_users", True, 1), ("all_users", False, 2)])
    def test_only_new_users_excludes_people_who_were_here_before(self, _name, only_new_users, expected_size):
        # Without this, a channel's cohorts are inflated by its own returning traffic and every channel's
        # week 0 reads larger than its true intake.
        create_person(team=self.team, distinct_ids=["new"])
        create_person(team=self.team, distinct_ids=["returning"])
        self._session("new", WEEK_0, utm_source="google")
        self._session("returning", BEFORE_RANGE, utm_source="google")
        self._session("returning", WEEK_0, utm_source="google")

        response = self._run(only_new_users=only_new_users)

        self.assertEqual(response.results[0].cohortSize, expected_size)

    def test_only_new_users_still_excludes_a_prior_direct_visitor_when_direct_is_excluded(self):
        # "Has this person been here before" must not be filtered by excludeDirectTraffic. If it were, a
        # user whose earlier visits were all direct would count as newly acquired by the paid channel
        # that re-touched them.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", BEFORE_RANGE, utm_source=None, referring_domain="$direct")
        self._session("p1", WEEK_0, utm_source="google", referring_domain="ads.example.com")

        response = self._run(exclude_direct=True)

        self.assertEqual(response.results, [])

    def test_conversion_goal_return_counts_conversions_not_pageviews(self):
        # Period 0 counts converters, which is why cohortSize can't be read off values[0]: this person is
        # in the cohort but converted only in week 2.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._session("p1", WEEK_1, utm_source="google")
        self._conversion("p1", WEEK_2)

        response = self._run(returning_event=MarketingAnalyticsRetentionReturningEvent.CONVERSION_GOAL)

        row = response.results[0]
        self.assertEqual(row.cohortSize, 1)
        self.assertEqual([cell.count for cell in row.values], [0, 0, 1, 0])
        self.assertEqual(response.conversionGoalName, "Purchases")

    @parameterized.expand(
        [
            (MarketingAnalyticsAttributionBreakdown.CHANNEL, {"referring_domain": None}),
            (MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN, {"referring_domain": "$direct"}),
            (MarketingAnalyticsAttributionBreakdown.CAMPAIGN, {}),
        ]
    )
    def test_exclude_unattributed_drops_the_sentinel_for_each_breakdown(self, breakdown, session_kwargs):
        # Each breakdown has its own idea of "names nothing": the channel classifier's Unknown, the
        # $direct referring-domain sentinel, and a plain empty campaign.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, **session_kwargs)

        self.assertEqual(self._run(breakdown, exclude_unattributed=True).results, [])
        self.assertEqual(len(self._run(breakdown, exclude_unattributed=False).results), 1)

    def test_breakdown_limit_folds_the_tail_into_other_and_keeps_the_sizes(self):
        for i in range(4):
            create_person(team=self.team, distinct_ids=[f"p{i}"])
            self._session(f"p{i}", WEEK_0, utm_source=f"source-{i}")

        response = self._run(breakdown_limit=2)

        rows = self._rows_by_value(response)
        self.assertEqual(response.otherBreakdownCount, 2)
        self.assertEqual(rows[BREAKDOWN_OTHER_STRING_LABEL][0].cohortSize, 2)
        self.assertEqual(response.totalCohortSize, 4)

    def test_activity_after_the_range_does_not_count(self):
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._session("p1", "2023-02-15T12:00:00Z", utm_source="google")

        response = self._run()

        self.assertEqual([cell.count for cell in response.results[0].values], [1, 0, 0, 0])

    def test_a_session_that_never_resolved_produces_no_cohort_row(self):
        # An unresolved session id yields an epoch-zero $start_timestamp rather than null, which would
        # bucket the person tens of thousands of periods before the range instead of being dropped.
        create_person(team=self.team, distinct_ids=["p1"])
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp=WEEK_0,
            properties={"$session_id": "not-a-uuid7", "$referring_domain": "$direct"},
        )

        response = self._run()

        self.assertEqual(response.results, [])

    @parameterized.expand(
        [
            (MarketingAnalyticsRetentionInterval.WEEK, 4),
            (MarketingAnalyticsRetentionInterval.MONTH, 1),
        ]
    )
    def test_interval_controls_the_cohort_grain(self, interval, expected_cohorts):
        for i, at in enumerate([WEEK_0, WEEK_1, WEEK_2, WEEK_3]):
            create_person(team=self.team, distinct_ids=[f"p{i}"])
            self._session(f"p{i}", at, utm_source="google")

        response = self._run(interval=interval)

        self.assertEqual(len({row.cohortIndex for row in response.results}), expected_cohorts)
        self.assertEqual(response.interval, interval)

    @parameterized.expand([("sunday_weeks", WeekStartDay.SUNDAY), ("monday_weeks", WeekStartDay.MONDAY)])
    def test_elapsed_periods_are_complete_and_unlived_ones_are_not(self, _name, week_start_day):
        # Two regressions in one. A period that has fully elapsed inside the range must not be greyed
        # out — `date_to` is the range's last instant, not its exclusive end, so comparing against it
        # directly marked the final column of every historical range as unfinished. And the newest
        # cohort's later columns must be greyed out, or weeks that haven't happened read as churn.
        # Parameterized over week start because that shifts every cohort boundary by a day.
        self.team.week_start_day = week_start_day
        self.team.save()
        create_person(team=self.team, distinct_ids=["early"])
        create_person(team=self.team, distinct_ids=["late"])
        self._session("early", WEEK_0, utm_source="google")
        self._session("late", DATE_TO + "T12:00:00Z", utm_source="google")

        response = self._run()

        by_index = {row.cohortIndex: row for row in response.results}
        oldest, newest = by_index[min(by_index)], by_index[max(by_index)]
        self.assertTrue(all(cell.complete for cell in oldest.values))
        # The newest cohort's last column sits past the end of the range under either week start, so
        # it's the one cell that must be greyed out whichever day weeks begin on.
        self.assertFalse(newest.values[-1].complete)

    def test_the_final_fully_elapsed_period_is_complete(self):
        # The narrowest form of the off-by-one: a single-cohort range that ended in the past. Comparing
        # the cohort's end against an inclusive `date_to` renders the whole table as "–".
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")

        response = self._run(date_from="2023-01-02", date_to="2023-01-08", total_intervals=1)

        self.assertTrue(response.results[0].values[0].complete)

    @freeze_time("2023-01-11T10:00:00Z")
    def test_the_period_still_being_lived_through_is_incomplete(self):
        # On an open-ended range `date_to` is the end of today, which is in the future, so comparing
        # against it alone marks today complete. At 10am that renders a third of a day's traffic as a
        # finished number, and a marketer reads the drop as churn. Only the wall clock closes a period.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", "2023-01-04T12:00:00Z", utm_source="google")

        response = self._run(
            date_from="-7d",
            date_to=None,
            interval=MarketingAnalyticsRetentionInterval.DAY,
            total_intervals=8,
        )

        row = next(r for r in response.results if r.cohortIndex == 0)
        # Column 6 covers yesterday and column 7 covers today. Asserting both ways so the test can't
        # pass by greying out everything.
        self.assertTrue(row.values[6].complete)
        self.assertFalse(row.values[7].complete)

    def test_cohorts_beyond_the_cap_are_dropped_and_reported(self):
        # The clamp also pulls the scan's lower bound forward, so the table silently covers less than the
        # date range the filter bar shows unless the dropped count comes back with it.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", "2023-03-01T12:00:00Z", utm_source="google")

        response = self._run(
            date_from="2023-01-01",
            date_to="2023-03-31",
            interval=MarketingAnalyticsRetentionInterval.DAY,
            total_intervals=1,
        )

        self.assertEqual(response.truncatedCohorts, 90 - MAX_COHORTS)
        self.assertTrue(all(0 <= row.cohortIndex < MAX_COHORTS for row in response.results))

    def test_an_inverted_date_range_returns_an_empty_table_instead_of_raising(self):
        # A range ending before it starts spans no periods. Every expression anchors on the first cohort
        # start, so an empty cohort list crashes the whole query on an index error rather than returning
        # the empty table the range describes.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")

        response = self._run(date_from="2023-03-01", date_to="2023-01-01")

        self.assertEqual(response.results, [])

    @parameterized.expand(
        [
            ("interval_count_negative", {"total_intervals": -1}, "interval_count", 1),
            ("interval_count_over_max", {"total_intervals": 9999}, "interval_count", MAX_TOTAL_INTERVALS),
            ("breakdown_limit_negative", {"breakdown_limit": -5}, "breakdown_limit", 1),
            ("breakdown_limit_over_max", {"breakdown_limit": 10_000}, "breakdown_limit", MAX_BREAKDOWN_LIMIT),
            ("lookback_over_max", {"new_user_lookback_days": 9999}, "new_user_lookback_days", 365),
        ]
    )
    def test_out_of_range_options_are_clamped_not_rejected(self, _name, overrides, attribute, expected):
        # These come from a query the frontend builds, so an out-of-range value is a bug to contain
        # rather than an error to show a marketer. A range wide enough that the interval clamp, not the
        # cohort count, is what bites.
        query = self._query(
            date_from="2023-01-01", date_to="2023-03-31", interval=MarketingAnalyticsRetentionInterval.DAY, **overrides
        )
        runner = MarketingAnalyticsRetentionQueryRunner(query=query, team=self.team)

        self.assertEqual(getattr(runner, attribute), expected)

    def test_the_widest_matrix_stays_under_the_printers_row_cap(self):
        # The outer select's limit is documented as a backstop that never truncates. It only holds while
        # the three clamps multiply out below the printer's cap — past that the printer silently keeps
        # the first 100k rows in breakdown-value order, dropping whole values off the end of the
        # alphabet, which is the exact failure folding exists to prevent.
        widest_matrix = (MAX_BREAKDOWN_LIMIT + 1) * MAX_COHORTS * MAX_TOTAL_INTERVALS + 1

        self.assertLessEqual(widest_matrix, MAX_SELECT_RETENTION_LIMIT)

    def test_folding_a_high_cardinality_breakdown_keeps_every_rate_under_one(self):
        # Landing page is the breakdown folding exists for. Sizes and cells fold through separate CTEs,
        # so a value landing in "Other" on one side and not the other gives a cell counting more people
        # than the cohort holds — a rate above 100%, from a table that otherwise looks fine.
        for i in range(6):
            create_person(team=self.team, distinct_ids=[f"p{i}"])
            self._session(f"p{i}", WEEK_0, path=f"/page-{i}")
            self._session(f"p{i}", WEEK_1, path=f"/page-{i}")

        response = self._run(MarketingAnalyticsAttributionBreakdown.LANDING_PAGE, breakdown_limit=2)

        rows = self._rows_by_value(response)
        self.assertEqual(len(rows), 3)
        self.assertEqual(response.otherBreakdownCount, 4)
        self.assertEqual(rows[BREAKDOWN_OTHER_STRING_LABEL][0].cohortSize, 4)
        self.assertEqual(response.totalCohortSize, 6)
        self.assertTrue(all(cell.rate is None or cell.rate <= 1.0 for row in response.results for cell in row.values))

    def test_converting_twice_in_one_period_counts_the_person_once(self):
        # Activity is collapsed to one row per person per period before the join. Losing that collapse
        # counts each conversion separately, so a cohort of repeat buyers retains above 100%.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._conversion("p1", WEEK_1)
        self._conversion("p1", "2023-01-12T12:00:00Z")

        response = self._run(returning_event=MarketingAnalyticsRetentionReturningEvent.CONVERSION_GOAL)

        row = response.results[0]
        self.assertEqual(row.values[1].count, 1)
        self.assertEqual(row.values[1].rate, 1.0)

    def test_a_goal_start_places_the_person_in_the_period_they_converted(self):
        # The point of the goal start: someone who arrived in week 0 and signed up in week 2 belongs to
        # the week 2 cohort, so the columns count from the signup. Keying the row off the arrival would
        # answer the question the arrival start already answers.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._signup("p1", WEEK_2)
        self._conversion("p1", WEEK_3)

        response = self._run(
            start_event=MarketingAnalyticsRetentionStartEvent.CONVERSION_GOAL,
            start_goal_id=SIGNUP_GOAL_ID,
            returning_event=MarketingAnalyticsRetentionReturningEvent.CONVERSION_GOAL,
        )

        row = response.results[0]
        self.assertEqual(row.cohortIndex, 2)
        # Purchased one period after signing up, and the two axes resolved different goals to get here.
        self.assertEqual([cell.count for cell in row.values], [0, 1, 0, 0])
        self.assertEqual(response.startConversionGoalName, "Sign ups")
        self.assertEqual(response.conversionGoalName, "Purchases")

    def test_a_goal_start_still_credits_the_channel_that_acquired_them(self):
        # The breakdown has to stay the acquiring channel even when the conversion happens in a later
        # session from somewhere else. Reading it off the converting session is the obvious alternative
        # and would make "Channel" mean something different here than on the attribution tab.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._session("p1", WEEK_1, utm_source="bing")
        self._conversion("p1", WEEK_1)

        response = self._run(start_event=MarketingAnalyticsRetentionStartEvent.CONVERSION_GOAL)

        self.assertEqual([row.breakdownValue for row in response.results], ["google"])

    def test_a_goal_start_does_not_count_browsing_that_led_up_to_the_conversion(self):
        # Period 0 must measure coming back, not the visit that produced the purchase. Comparing only
        # period indexes lets a pageview from earlier the same week through, so the column that answers
        # "do the people who convert stay?" would read near 100% for everyone.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", "2023-01-09T09:00:00Z", utm_source="google")
        self._conversion("p1", "2023-01-09T17:00:00Z")

        response = self._run(start_event=MarketingAnalyticsRetentionStartEvent.CONVERSION_GOAL)

        row = response.results[0]
        self.assertEqual(row.cohortSize, 1)
        self.assertEqual([cell.count for cell in row.values], [0, 0, 0, 0])

    def test_a_goal_start_ignores_a_conversion_that_precedes_the_attributed_session(self):
        # The breakdown comes from the first session that survives the touchpoint filters, so with
        # direct excluded that session can land after a conversion the person already made. Keying the
        # cohort off that earlier conversion credits a channel whose only touch came later.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source=None, referring_domain="$direct")
        self._conversion("p1", WEEK_0)
        self._session("p1", WEEK_2, utm_source="google", referring_domain="ads.example.com")
        self._conversion("p1", WEEK_2)

        response = self._run(
            start_event=MarketingAnalyticsRetentionStartEvent.CONVERSION_GOAL,
            exclude_direct=True,
            only_new_users=False,
        )

        # Cohorted on the week 2 conversion, the first one at or after the session being credited.
        self.assertEqual([row.cohortIndex for row in response.results], [2])

    def test_a_goal_start_keys_off_the_first_conversion_not_a_later_one(self):
        # A repeat converter must not have their row move every time they convert again.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._conversion("p1", WEEK_1)
        self._conversion("p1", WEEK_3)

        response = self._run(start_event=MarketingAnalyticsRetentionStartEvent.CONVERSION_GOAL)

        self.assertEqual([row.cohortIndex for row in response.results], [1])

    def test_converting_then_converting_again_shows_up_as_a_later_column(self):
        # The fourth quadrant end to end: cohorted on the goal and counting the same goal, which is how
        # "do the people who pay keep paying" gets asked.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", WEEK_0, utm_source="google")
        self._conversion("p1", WEEK_1)
        self._conversion("p1", WEEK_2)

        response = self._run(
            start_event=MarketingAnalyticsRetentionStartEvent.CONVERSION_GOAL,
            returning_event=MarketingAnalyticsRetentionReturningEvent.CONVERSION_GOAL,
        )

        row = response.results[0]
        self.assertEqual(row.cohortIndex, 1)
        self.assertEqual([cell.count for cell in row.values], [1, 1, 0, 0])

    def test_a_goal_start_leaves_out_someone_acquired_before_the_range(self):
        # A known limitation, kept honest here: the breakdown is read off an in-range first session, so
        # a person who converted inside the range but arrived before it has no channel to credit and
        # drops out. Loosening the join to keep them would silently report them as unattributed.
        create_person(team=self.team, distinct_ids=["old"])
        create_person(team=self.team, distinct_ids=["new"])
        self._session("old", BEFORE_RANGE, utm_source="google")
        self._conversion("old", WEEK_1)
        self._session("new", WEEK_0, utm_source="google")
        self._conversion("new", WEEK_1)

        response = self._run(start_event=MarketingAnalyticsRetentionStartEvent.CONVERSION_GOAL, only_new_users=False)

        self.assertEqual(sum(row.cohortSize for row in response.results), 1)

    def test_property_filters_narrow_the_cohort_and_the_return(self):
        # The filters have to reach both arms. Applied only to the cohort side, a filtered-out person
        # still fills return cells; applied only to the return side, they inflate the cohort instead.
        create_person(team=self.team, distinct_ids=["desktop"])
        create_person(team=self.team, distinct_ids=["mobile"])
        for distinct_id, device in (("desktop", "Desktop"), ("mobile", "Mobile")):
            for at in (WEEK_0, WEEK_1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=at,
                    properties={
                        "$session_id": str(uuid7(at)),
                        "$referring_domain": "$direct",
                        "utm_source": "google",
                        "$device_type": device,
                    },
                )

        response = self._run(
            properties=[EventPropertyFilter(key="$device_type", value=["Desktop"], operator=PropertyOperator.EXACT)]
        )

        row = response.results[0]
        self.assertEqual(row.cohortSize, 1)
        self.assertEqual([cell.count for cell in row.values], [1, 1, 0, 0])
