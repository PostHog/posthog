from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    ConversionGoalFilter1,
    DateRange,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionQuery,
    PropertyMathType,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.test.persons import create_person

from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    SESSION_FORWARD_PAD_MINUTES,
    ensure_marketing_sessions_precomputed,
)

GOAL_ID = "goal-1"
CONVERSION_EVENT = "purchase"
WINDOW_DAYS = 4

DATE_FROM = "2023-01-10"
DATE_TO = "2023-01-20"
# The read extends the display range back by the attribution window, so this is its lower edge.
WINDOW_START = datetime(2023, 1, 10, tzinfo=UTC) - timedelta(days=WINDOW_DAYS)


class TestAttributionSessionsPrecomputeParity(ClickhouseTestMixin, BaseTest):
    """The precomputed read must agree with the live scan, including at the window edge.

    The generated fixture data elsewhere gives every session a single timestamp, so a session's
    start and its last event coincide and the two paths cannot disagree. These sessions span real
    time, which is what makes the bound observable.
    """

    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
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
                math=PropertyMathType.SUM,
                math_property="revenue",
                counts_as_revenue=True,
            ).model_dump()
        ]
        config.save()

    def _session(self, distinct_id: str, opened_at: datetime, *, campaign: str, event_offsets_minutes: list[int]):
        """A session opening at `opened_at` with a pageview at each offset after it."""
        session_id = str(uuid7(opened_at.strftime("%Y-%m-%dT%H:%M:%SZ")))
        for offset in event_offsets_minutes:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=(opened_at + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                properties={
                    "$session_id": session_id,
                    "$current_url": "https://example.com/",
                    "$pathname": "/",
                    "$referring_domain": "$direct",
                    "utm_campaign": campaign,
                },
            )

    def _conversion(self, distinct_id: str, at: datetime):
        _create_event(
            team=self.team,
            event=CONVERSION_EVENT,
            distinct_id=distinct_id,
            timestamp=at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            properties={"revenue": 100.0},
        )

    def _run(self, breakdown: MarketingAnalyticsAttributionBreakdown, *, precomputed: bool):
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            breakdownBy=breakdown,
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team)
        runner.config.sessions_precomputation_enabled = precomputed
        response = runner.calculate()
        rows = {row.breakdownValue: (row.visitors, row.influencedConversions) for row in (response.results or [])}
        return rows, runner._sessions_precompute_used

    def _materialize(self):
        # Same extended lower edge the reader asks for, so a session that opened before the window
        # has its chunk built.
        result = ensure_marketing_sessions_precomputed(
            self.team,
            WINDOW_START - timedelta(minutes=SESSION_FORWARD_PAD_MINUTES),
            datetime(2023, 1, 20, 23, 59, 59, tzinfo=UTC),
        )
        assert result.ready, result.errors
        return result

    @parameterized.expand(
        [
            ("campaign", MarketingAnalyticsAttributionBreakdown.CAMPAIGN),
            ("channel", MarketingAnalyticsAttributionBreakdown.CHANNEL),
        ]
    )
    def test_session_open_before_the_window_with_events_inside_it_counts_in_both_paths(
        self, _name: str, breakdown: MarketingAnalyticsAttributionBreakdown
    ):
        # The live scan keeps a session whose events land in the window and reports its start as the
        # touchpoint. Bounding the precomputed read by session start instead dropped this person from
        # the denominator and moved their first-touch credit.
        create_person(team=self.team, distinct_ids=["straddler"])
        self._session(
            "straddler", WINDOW_START - timedelta(minutes=30), campaign="straddle", event_offsets_minutes=[0, 60]
        )
        self._conversion("straddler", datetime(2023, 1, 12, 12, 0, tzinfo=UTC))

        create_person(team=self.team, distinct_ids=["inside"])
        self._session(
            "inside", datetime(2023, 1, 11, 9, 0, tzinfo=UTC), campaign="inside", event_offsets_minutes=[0, 15]
        )
        self._conversion("inside", datetime(2023, 1, 12, 12, 0, tzinfo=UTC))
        flush_persons_and_events()

        live, live_used = self._run(breakdown, precomputed=False)
        self._materialize()
        pre, pre_used = self._run(breakdown, precomputed=True)

        assert not live_used
        assert pre_used, "the precomputed path was not used, so this proves nothing"
        assert pre == live, f"precomputed={pre} live={live}"

    def test_a_session_stored_under_two_jobs_is_one_touchpoint(self):
        # A session's stored start is the earliest event seen when its chunk ran. A later event that
        # predates it moves the start, filing the session under a different chunk while the first
        # chunk's row survives. Both jobs are read, and without a collapse the person is credited
        # twice for one session.
        create_person(team=self.team, distinct_ids=["dup"])
        self._session("dup", datetime(2023, 1, 11, 9, 0, tzinfo=UTC), campaign="dup", event_offsets_minutes=[0, 20])
        self._conversion("dup", datetime(2023, 1, 12, 12, 0, tzinfo=UTC))
        flush_persons_and_events()

        result = self._materialize()
        rows = sync_execute(
            "SELECT session_id, person_id, start_timestamp, job_id, computed_at, channel_type, utm_campaign, "
            "utm_source, utm_medium, utm_term, utm_content, referring_domain, entry_pathname, period_bucket, "
            "min_event_timestamp, max_event_timestamp, expires_at "
            "FROM marketing_sessions_dimensional_preaggregated WHERE team_id = %(team)s AND utm_campaign = 'dup'",
            {"team": self.team.pk},
        )
        assert len(rows) == 1, rows
        original = rows[0]

        # A second row for the same session under another job in the ready set. A backdated event moves
        # the session start, and the entry properties are argMin by timestamp, so the re-materialized
        # row can carry a different campaign. That is the damaging shape: one session landing in two
        # campaigns, splitting the person across rows that should be one.
        second_job = next(iter(result.job_ids))
        sync_execute(
            """
            INSERT INTO marketing_sessions_dimensional_preaggregated
            (team_id, job_id, period_bucket, session_id, person_id, start_timestamp, min_event_timestamp,
             max_event_timestamp, channel_type, utm_source, utm_medium, utm_campaign, utm_term, utm_content,
             referring_domain, entry_pathname, computed_at, expires_at)
            VALUES (%(team)s, %(job)s, %(bucket)s, %(sid)s, %(pid)s, %(start)s, %(min_ev)s, %(max_ev)s,
                    %(chan)s, %(src)s, %(med)s, %(camp)s, %(term)s, %(content)s, %(ref)s, %(path)s,
                    %(computed)s, %(expires)s)
            """,
            {
                "team": self.team.pk,
                "job": str(second_job),
                "bucket": original[13],
                "sid": original[0],
                "pid": original[1],
                # earlier start, as a backdated event would produce
                "start": original[2] - timedelta(minutes=45),
                "min_ev": original[14] - timedelta(minutes=45),
                "max_ev": original[15],
                "chan": original[5],
                "src": original[7],
                "med": original[8],
                "camp": "dup_superseded",
                "term": original[9],
                "content": original[10],
                "ref": original[11],
                "path": original[12],
                "computed": original[4] + timedelta(minutes=1),
                "expires": original[16],
            },
        )
        stored = sync_execute(
            "SELECT count() FROM marketing_sessions_dimensional_preaggregated "
            "WHERE team_id = %(team)s AND session_id = %(sid)s",
            {"team": self.team.pk, "sid": original[0]},
        )[0][0]
        assert stored == 2, "the fixture must leave two rows for one session, or it proves nothing"

        rows_out, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=True)
        assert used
        # The newer row supersedes the older one, so the person sits in exactly one campaign.
        assert "dup" not in rows_out, f"the superseded campaign is still credited: {rows_out}"
        assert rows_out.get("dup_superseded") == (1, 1), rows_out
