from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import (
    ConversionGoalFilter1,
    DateRange,
    HogQLQueryModifiers,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionPathsQuery,
    MarketingAnalyticsAttributionQuery,
    MarketingAnalyticsAttributionQueryResponse,
    PersonsOnEventsMode,
    PropertyMathType,
    SessionTableVersion,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tags_context
from posthog.dataclasses import frozen
from posthog.models.utils import uuid7
from posthog.test.persons import add_distinct_id, create_person

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.analytics_platform.backend.models import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries import attribution_sessions_read
from products.marketing_analytics.backend.hogql_queries.attribution_paths_query_runner import (
    MarketingAnalyticsAttributionPathsQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    SESSION_READ_REACHBACK_DAYS,
    ensure_marketing_sessions_precomputed,
)
from products.marketing_analytics.backend.tasks.lazy_precompute_revalidation import (
    revalidate_marketing_analytics_precompute,
)

GOAL_ID = "goal-1"
CONVERSION_EVENT = "purchase"
WINDOW_DAYS = 4

DATE_FROM = "2023-01-10"
DATE_TO = "2023-01-20"
# The read extends the display range back by the attribution window, so this is its lower edge.
WINDOW_START = datetime(2023, 1, 10, tzinfo=UTC) - timedelta(days=WINDOW_DAYS)


@frozen
class _AttributionCounts:
    visitors: int
    conversions: int


class TestAttributionSessionsPrecomputeParity(ClickhouseTestMixin, BaseTest):
    """The precomputed read must agree with the live scan, including at the window edge.

    The generated fixture data elsewhere gives every session a single timestamp, so a session's
    start and its last event coincide and the two paths cannot disagree. These sessions span real
    time, which is what makes the bound observable.
    """

    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
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

    def _session(
        self,
        distinct_id: str,
        opened_at: datetime,
        *,
        campaign: str,
        event_offsets_minutes: list[int],
        source: Optional[str] = None,
    ) -> None:
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
                    "$referring_domain": "$direct" if source is None else "www.google.com",
                    "utm_campaign": campaign,
                    **({"utm_source": source, "utm_medium": "cpc"} if source else {}),
                },
            )

    def _conversion(self, distinct_id: str, at: datetime) -> None:
        _create_event(
            team=self.team,
            event=CONVERSION_EVENT,
            distinct_id=distinct_id,
            timestamp=at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            properties={"revenue": 100.0},
        )

    def _run(
        self,
        breakdown: MarketingAnalyticsAttributionBreakdown,
        *,
        precomputed: bool,
        exclude_direct: bool = False,
        allow_multiple_conversions: bool | None = None,
        modifiers: HogQLQueryModifiers | None = None,
    ) -> tuple[dict[str, _AttributionCounts], bool]:
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            breakdownBy=breakdown,
            conversionGoalId=GOAL_ID,
            properties=[],
            excludeDirectTraffic=exclude_direct,
            allowMultipleConversionsPerVisitor=allow_multiple_conversions,
            modifiers=modifiers,
        )
        runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team)
        runner.config.sessions_precomputation_enabled = precomputed
        response = runner.calculate()
        rows = {
            row.breakdownValue: _AttributionCounts(visitors=row.visitors, conversions=row.influencedConversions)
            for row in (response.results or [])
        }
        return rows, runner._sessions_precompute_used

    def _materialize(self) -> LazyComputationResult:
        # Same extended lower edge the reader asks for, so a session that opened before the window
        # has its chunk built.
        result = ensure_marketing_sessions_precomputed(
            self.team,
            WINDOW_START - timedelta(days=SESSION_READ_REACHBACK_DAYS),
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
    ) -> None:
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

    def test_a_session_stored_under_two_jobs_is_one_touchpoint(self) -> None:
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
            "SELECT session_id_v7, person_id, start_timestamp, job_id, computed_at, channel_type, utm_campaign, "
            "utm_source, utm_medium, utm_term, utm_content, referring_domain, entry_pathname, period_bucket, "
            "min_event_timestamp, max_event_timestamp, expires_at "
            "FROM web_sessions_dimensional_preaggregated WHERE team_id = %(team)s AND utm_campaign = 'dup'",
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
            INSERT INTO web_sessions_dimensional_preaggregated
            (team_id, job_id, period_bucket, session_id_v7, person_id, start_timestamp, min_event_timestamp,
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
                "sid": str(original[0]),
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
            "SELECT count() FROM web_sessions_dimensional_preaggregated "
            "WHERE team_id = %(team)s AND session_id_v7 = toUInt128(%(sid)s)",
            {"team": self.team.pk, "sid": str(original[0])},
        )[0][0]
        assert stored == 2, "the fixture must leave two rows for one session, or it proves nothing"

        rows_out, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=True)
        assert used
        # The newer row supersedes the older one, so the person sits in exactly one campaign.
        assert "dup" not in rows_out, f"the superseded campaign is still credited: {rows_out}"
        assert rows_out.get("dup_superseded") == _AttributionCounts(visitors=1, conversions=1), rows_out

    # Both paths hold their own reference to the ceiling, so both have to be lowered for the fixture
    # to stay small enough to read.
    @parameterized.expand([("repeat", True), ("first_only", False)])
    @patch("products.marketing_analytics.backend.hogql_queries.attribution_base.MAX_CONVERSIONS_PER_PERSON", 2)
    @patch("products.marketing_analytics.backend.hogql_queries.attribution_sessions_read.MAX_CONVERSIONS_PER_PERSON", 2)
    def test_a_person_over_the_conversion_ceiling_is_attributed_the_same_on_both_paths(
        self, _name: str, allow_multiple_conversions: bool
    ) -> None:
        # The live path caps how many of one person's conversions can earn credit, because the two
        # downstream ARRAY JOINs multiply without bound otherwise. A precomputed read that skipped the
        # cap would both diverge here and reopen that growth.
        create_person(team=self.team, distinct_ids=["heavy"])
        self._session("heavy", datetime(2023, 1, 11, 9, 0, tzinfo=UTC), campaign="heavy", event_offsets_minutes=[0])
        for hour in (10, 11, 12):
            self._conversion("heavy", datetime(2023, 1, 12, hour, 0, tzinfo=UTC))
        flush_persons_and_events()

        live, live_used = self._run(
            MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
            precomputed=False,
            allow_multiple_conversions=allow_multiple_conversions,
        )
        self._materialize()
        pre, pre_used = self._run(
            MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
            precomputed=True,
            allow_multiple_conversions=allow_multiple_conversions,
        )

        assert not live_used
        assert pre_used, "the precomputed path was not used, so this proves nothing"
        assert pre == live, f"precomputed={pre} live={live}"

    def test_a_test_account_filter_falls_back_to_the_live_scan(self) -> None:
        # The stored rows hold internal and external traffic together, and the touchpoint side never
        # scans `events`, so the filter has nothing to apply to. Reading them anyway counted the
        # internal visitor in the denominator and credited their conversion.
        self.team.test_account_filters = [
            {"key": "email", "value": "@internal.example.com", "operator": "not_icontains", "type": "person"}
        ]
        self.team.save()
        self.team.marketing_analytics_config.filter_test_accounts = True
        self.team.marketing_analytics_config.save()
        create_person(team=self.team, distinct_ids=["buyer"], properties={"email": "buyer@example.com"})
        create_person(team=self.team, distinct_ids=["staff"], properties={"email": "qa@internal.example.com"})
        for distinct_id in ("buyer", "staff"):
            self._session(
                distinct_id,
                datetime(2023, 1, 11, 9, 0, tzinfo=UTC),
                campaign="shared",
                event_offsets_minutes=[0],
                source="google",
            )
            self._conversion(distinct_id, datetime(2023, 1, 12, 12, 0, tzinfo=UTC))
        flush_persons_and_events()

        live, live_used = self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, precomputed=False)
        self._materialize()
        pre, pre_used = self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, precomputed=True)

        # Pinned, so the fixture proves the internal person was dropped rather than never seeded.
        assert live == {"google": _AttributionCounts(visitors=1, conversions=1)}, live
        assert not pre_used, "the precompute answered a query whose filter it cannot honor"
        assert pre == live, f"precomputed={pre} live={live}"

    def test_an_exclusion_judges_the_current_version_of_a_session(self) -> None:
        # A session's rows can disagree: the stored start moves when a backdated event arrives, and the
        # re-materialized row can carry different dimensions. Filtering the raw rows drops the current
        # version and leaves the superseded one standing, so a session that is Direct today would keep
        # earning credit under the campaign it used to carry.
        create_person(team=self.team, distinct_ids=["flipped"])
        self._session(
            "flipped",
            datetime(2023, 1, 11, 9, 0, tzinfo=UTC),
            campaign="was_a_campaign",
            event_offsets_minutes=[0],
            source="google",
        )
        self._conversion("flipped", datetime(2023, 1, 12, 12, 0, tzinfo=UTC))
        flush_persons_and_events()
        self._materialize()

        original = sync_execute(
            "SELECT session_id_v7, person_id, start_timestamp, job_id, computed_at, period_bucket, "
            "min_event_timestamp, max_event_timestamp, expires_at "
            "FROM web_sessions_dimensional_preaggregated WHERE team_id = %(team)s AND utm_campaign = 'was_a_campaign'",
            {"team": self.team.pk},
        )[0]
        sync_execute(
            """
            INSERT INTO web_sessions_dimensional_preaggregated
            (team_id, job_id, period_bucket, session_id_v7, person_id, start_timestamp, min_event_timestamp,
             max_event_timestamp, channel_type, utm_source, utm_medium, utm_campaign, utm_term, utm_content,
             referring_domain, entry_pathname, computed_at, expires_at)
            VALUES (%(team)s, %(job)s, %(bucket)s, %(sid)s, %(pid)s, %(start)s, %(min_ev)s, %(max_ev)s,
                    'Direct', '', '', '', '', '', '', '/', %(computed)s, %(expires)s)
            """,
            {
                "team": self.team.pk,
                "job": str(original[3]),
                "bucket": original[5],
                "sid": str(original[0]),
                "pid": original[1],
                "start": original[2],
                "min_ev": original[6],
                "max_ev": original[7],
                "computed": original[4] + timedelta(minutes=1),
                "expires": original[8],
            },
        )

        rows, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=True, exclude_direct=True)
        assert used, "the precomputed path was not used, so this proves nothing"
        assert "was_a_campaign" not in rows, f"the superseded campaign survived the exclusion: {rows}"

    def test_session_starting_before_reachback_falls_back_without_losing_reach(self) -> None:
        create_person(team=self.team, distinct_ids=["long-session"])
        self._session(
            "long-session", WINDOW_START - timedelta(hours=48), campaign="long", event_offsets_minutes=[0, 49 * 60]
        )
        self._conversion("long-session", datetime(2023, 1, 12, 12, tzinfo=UTC))
        flush_persons_and_events()
        live, _ = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=False)
        self._materialize()
        pre, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=True)
        assert not used
        assert live.get("long") == _AttributionCounts(visitors=1, conversions=0)
        assert pre == live

    @time_machine.travel("2026-09-11T12:00:00Z", tick=False)
    def test_expired_jobs_are_served_with_grace_and_revalidation_rebuilds_them(self) -> None:
        create_person(team=self.team, distinct_ids=["stale-session"])
        self._session(
            "stale-session", datetime(2023, 1, 11, 9, tzinfo=UTC), campaign="stale", event_offsets_minutes=[0]
        )
        self._conversion("stale-session", datetime(2023, 1, 12, 12, tzinfo=UTC))
        flush_persons_and_events()
        original = self._materialize()
        PreaggregationJob.objects.filter(team=self.team, id__in=original.job_ids).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        with patch.object(attribution_sessions_read, "serve_stale_enabled", return_value=False):
            live, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=True)
            assert not used
        with (
            patch.object(attribution_sessions_read, "serve_stale_enabled", return_value=True),
            patch.object(attribution_sessions_read, "handle_stale_served") as enqueue,
        ):
            stale, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=True)
            assert used
            assert stale == live
            enqueue.assert_called_once()
            query = enqueue.call_args.kwargs["query"]
            runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team)
            runner.config.sessions_precomputation_enabled = True
            with (
                tags_context(),
                patch(
                    "products.marketing_analytics.backend.tasks.lazy_precompute_revalidation.get_query_runner",
                    return_value=runner,
                ),
            ):
                revalidate_marketing_analytics_precompute(self.team.pk, query.model_dump())
            assert runner._sessions_precompute_used
            assert set(runner._sessions_precompute_jobs or []).isdisjoint(map(str, original.job_ids))
            enqueue.assert_called_once()
        with patch.object(attribution_sessions_read, "serve_stale_enabled", return_value=False):
            fresh, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, precomputed=True)
        assert used
        assert fresh == live

    @parameterized.expand(
        [
            (state, version)
            for state in ("merged", "override_first", "mapping_first", "split", "squashed")
            for version in (SessionTableVersion.V2, SessionTableVersion.V3)
        ]
    )
    def test_cached_dimensions_follow_current_event_identity(self, state: str, version: SessionTableVersion) -> None:
        self.team.modifiers = {
            "sessionTableVersion": version,
            "personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
        }
        create_person(team=self.team, distinct_ids=["anonymous", "second-device"])
        identified = create_person(team=self.team, distinct_ids=["identified"])
        self._session(
            "anonymous", datetime(2023, 1, 11, 9, tzinfo=UTC), campaign="first", event_offsets_minutes=[0, 10]
        )
        self._session(
            "second-device", datetime(2023, 1, 11, 10, tzinfo=UTC), campaign="second", event_offsets_minutes=[0, 10]
        )
        self._conversion("identified", datetime(2023, 1, 12, 12, tzinfo=UTC))
        flush_persons_and_events()
        result = self._materialize()
        stored_before = sync_execute(
            "SELECT * FROM web_sessions_dimensional_preaggregated WHERE team_id = %(team)s ORDER BY session_id_v7",
            {"team": self.team.pk},
        )
        self.assertTrue(stored_before)

        def override(distinct_id: str, person_id: UUID, version: int, deleted: bool = False) -> None:
            sync_execute(
                "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted) VALUES",
                [(self.team.pk, distinct_id, person_id, version, int(deleted))],
            )

        moving_ids = ["anonymous"] if state == "split" else ["anonymous", "second-device"]
        for distinct_id in moving_ids:
            if state != "override_first":
                add_distinct_id(person=identified, distinct_id=distinct_id, version=1)
            if state != "mapping_first":
                override(distinct_id, identified.uuid, 1)
            if state == "squashed":
                sync_execute(
                    "ALTER TABLE sharded_events UPDATE person_id = %(person)s "
                    "WHERE team_id = %(team)s AND distinct_id = %(distinct)s SETTINGS mutations_sync = 2",
                    {"person": identified.uuid, "team": self.team.pk, "distinct": distinct_id},
                )
                override(distinct_id, identified.uuid, 2, deleted=True)

        query_args = {
            "dateRange": DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            "breakdownBy": MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
            "conversionGoalId": GOAL_ID,
            "properties": [],
        }
        for query_type, runner_type in (
            (MarketingAnalyticsAttributionQuery, MarketingAnalyticsAttributionQueryRunner),
            (MarketingAnalyticsAttributionPathsQuery, MarketingAnalyticsAttributionPathsQueryRunner),
        ):
            responses = []
            for precomputed in (False, True):
                runner = runner_type(query=query_type(**query_args), team=self.team)
                runner.config.sessions_precomputation_enabled = precomputed
                response = runner.calculate()
                self.assertEqual(runner._sessions_precompute_used, precomputed)
                responses.append(response.results)
                if isinstance(response, MarketingAnalyticsAttributionQueryResponse):
                    self.assertEqual(response.totalConversions, 1)
                    self.assertEqual(response.unattributedConversions, 1 if state == "mapping_first" else 0)
                else:
                    self.assertEqual(response.attributedConversions, 0 if state == "mapping_first" else 1)
            self.assertCountEqual(responses[0], responses[1])

        stored_after = sync_execute(
            "SELECT * FROM web_sessions_dimensional_preaggregated WHERE team_id = %(team)s ORDER BY session_id_v7",
            {"team": self.team.pk},
        )
        self.assertEqual(stored_after, stored_before)
        hit = ensure_marketing_sessions_precomputed(
            self.team,
            WINDOW_START - timedelta(days=SESSION_READ_REACHBACK_DAYS),
            datetime(2023, 1, 20, 23, 59, 59, tzinfo=UTC),
            run_inserts=False,
        )
        self.assertTrue(hit.ready)
        self.assertEqual(set(hit.job_ids), set(result.job_ids))

    @parameterized.expand(
        [
            (SessionTableVersion.V2, SessionTableVersion.V3, False, "google"),
            (SessionTableVersion.V3, SessionTableVersion.V2, False, "old"),
            (SessionTableVersion.AUTO, SessionTableVersion.V2, True, "old"),
            (SessionTableVersion.V2, SessionTableVersion.AUTO, True, "old"),
            (SessionTableVersion.V3, SessionTableVersion.V3, True, "google"),
        ]
    )
    def test_query_session_version_matches_cached_dimensions(
        self, team_version: SessionTableVersion, query_version: SessionTableVersion, expected_cached: bool, source: str
    ) -> None:
        self.team.modifiers = {"sessionTableVersion": team_version}
        opened_at = datetime(2023, 1, 11, 9, tzinfo=UTC)
        session_id = str(uuid7(opened_at.strftime("%Y-%m-%dT%H:%M:%SZ")))
        create_person(team=self.team, distinct_ids=["version-override"])
        for event, offset, utm_source in [("$autocapture", 0, "old"), ("$pageview", 1, "google")]:
            _create_event(
                team=self.team,
                distinct_id="version-override",
                event=event,
                timestamp=opened_at + timedelta(minutes=offset),
                properties={"$session_id": session_id, "utm_source": utm_source, "utm_medium": "cpc"},
            )
        self._conversion("version-override", datetime(2023, 1, 12, 12, tzinfo=UTC))
        flush_persons_and_events()
        self._materialize()
        modifiers = HogQLQueryModifiers(sessionTableVersion=query_version)
        live, _ = self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, precomputed=False, modifiers=modifiers)
        cached, used = self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, precomputed=True, modifiers=modifiers)
        assert used is expected_cached
        assert cached == live == {source: _AttributionCounts(visitors=1, conversions=1)}

    @parameterized.expand(["start", "end"])
    def test_ambiguous_date_boundary_preserves_live_attribution(self, boundary: str) -> None:
        self.team.timezone = "America/New_York"
        date_range = DateRange(
            date_from="2025-11-02T01:30:00-05:00" if boundary == "start" else "2025-11-01T00:00:00-04:00",
            date_to="2025-11-02T01:30:00-05:00" if boundary == "end" else "2025-11-03T00:00:00-05:00",
            explicitDate=True,
        )
        create_person(team=self.team, distinct_ids=["ambiguous-boundary"])
        pageview_at = (
            datetime(2025, 10, 29, 6, tzinfo=UTC) if boundary == "start" else datetime(2025, 11, 2, 6, tzinfo=UTC)
        )
        session_id = str(uuid7(pageview_at.strftime("%Y-%m-%dT%H:%M:%SZ")))
        _create_event(
            team=self.team,
            distinct_id="ambiguous-boundary",
            event="$pageview",
            timestamp=pageview_at,
            properties={"$session_id": session_id, "utm_campaign": "boundary"},
        )
        if boundary == "end":
            _create_event(
                team=self.team,
                distinct_id="ambiguous-boundary",
                event="$autocapture",
                timestamp=datetime(2025, 11, 2, 4, tzinfo=UTC),
                properties={"$session_id": session_id, "utm_campaign": "boundary"},
            )
        self._conversion("ambiguous-boundary", datetime(2025, 11, 2, 5, 40 if boundary == "start" else 0, tzinfo=UTC))
        flush_persons_and_events()
        materialized = ensure_marketing_sessions_precomputed(
            self.team, datetime(2025, 10, 27, tzinfo=UTC), datetime(2025, 11, 4, tzinfo=UTC)
        )
        assert materialized.ready, materialized.errors
        for query_type, runner_type in (
            (MarketingAnalyticsAttributionQuery, MarketingAnalyticsAttributionQueryRunner),
            (MarketingAnalyticsAttributionPathsQuery, MarketingAnalyticsAttributionPathsQueryRunner),
        ):
            responses = []
            for precomputed in (False, True):
                runner = runner_type(
                    query=query_type(
                        dateRange=date_range,
                        breakdownBy=MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
                        conversionGoalId=GOAL_ID,
                        properties=[],
                    ),
                    team=self.team,
                )
                runner.config.sessions_precomputation_enabled = precomputed
                response = runner.calculate()
                assert not runner._sessions_precompute_used
                assert response.totalConversions == 1
                responses.append(response.results)
            self.assertCountEqual(responses[0], responses[1])

    @parameterized.expand(
        [
            (goal, explicit, version)
            for goal in ("purchase", "$pageview")
            for explicit in (False, True)
            for version in (SessionTableVersion.V2, SessionTableVersion.V3)
        ]
    )
    def test_fractional_boundary_events_match_conversion_date_precision(
        self, goal: str, explicit: bool, version: SessionTableVersion
    ) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        config = self.team.marketing_analytics_config
        config.conversion_goals[0]["event"] = goal
        config.save()
        end = datetime(2023, 1, 20, 23, 59, 59, tzinfo=UTC)
        for distinct_id, at, converts in [
            ("reach-only", end + timedelta(microseconds=500000), False),
            ("boundary", end + timedelta(microseconds=500000), True),
            ("start", datetime(2023, 1, 10, 0, 0, 0, 250000, tzinfo=UTC), True),
            ("excluded", end + timedelta(seconds=1), True),
        ]:
            create_person(team=self.team, distinct_ids=[distinct_id])
            _create_event(
                team=self.team,
                distinct_id=distinct_id,
                event="$pageview",
                timestamp=at,
                properties={
                    "$session_id": str(uuid7(at.strftime("%Y-%m-%dT%H:%M:%SZ"))),
                    "utm_campaign": distinct_id,
                    "revenue": 100,
                },
            )
            if converts and goal == "purchase":
                _create_event(
                    team=self.team,
                    distinct_id=distinct_id,
                    event=goal,
                    timestamp=at + timedelta(microseconds=100000),
                    properties={"revenue": 100},
                )
        flush_persons_and_events()
        self._materialize()
        date_range = DateRange(
            date_from="2023-01-10T00:00:00.750000Z" if explicit else DATE_FROM,
            date_to="2023-01-20T23:59:59.250000Z" if explicit else DATE_TO,
            explicitDate=explicit,
        )
        expected_conversions = 3 if goal == "$pageview" else 2
        for query_type, runner_type in (
            (MarketingAnalyticsAttributionQuery, MarketingAnalyticsAttributionQueryRunner),
            (MarketingAnalyticsAttributionPathsQuery, MarketingAnalyticsAttributionPathsQueryRunner),
        ):
            results = []
            for precomputed in (False, True):
                query = query_type(
                    dateRange=date_range,
                    breakdownBy=MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
                    conversionGoalId=GOAL_ID,
                    properties=[],
                )
                runner = runner_type(query=query, team=self.team)
                runner.config.sessions_precomputation_enabled = precomputed
                response = runner.calculate()
                assert runner._sessions_precompute_used is precomputed
                assert response.totalConversions == expected_conversions
                if isinstance(response, MarketingAnalyticsAttributionQueryResponse):
                    assert response.unattributedConversions == 0
                    rows = {row.breakdownValue: row.visitors for row in response.results or []}
                    assert rows == {"reach-only": 1, "boundary": 1, "start": 1}, (precomputed, rows)
                else:
                    assert response.attributedConversions == expected_conversions
                results.append(response.results)
            self.assertCountEqual(results[0], results[1])
