from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.conf import settings

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

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.models.utils import uuid7
from posthog.test.persons import add_distinct_id, create_person

from products.analytics_platform.backend.models import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries.attribution_paths_query_runner import (
    MarketingAnalyticsAttributionPathsQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
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


class TestAttributionSessionsParity(ClickhouseTestMixin, BaseTest):
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
    ) -> UUID:
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
                    "utm_term": "brand",
                    "utm_content": "hero",
                    **({"utm_source": source, "utm_medium": "cpc"} if source else {}),
                },
            )

        return UUID(session_id)

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
        live_resolution: bool,
        exclude_direct: bool = False,
        exclude_unattributed: bool = False,
        allow_multiple_conversions: bool | None = None,
        modifiers: HogQLQueryModifiers | None = None,
    ) -> tuple[dict[str, _AttributionCounts], bool]:
        query = MarketingAnalyticsAttributionQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            breakdownBy=breakdown,
            conversionGoalId=GOAL_ID,
            properties=[],
            excludeDirectTraffic=exclude_direct,
            excludeUnattributed=exclude_unattributed,
            allowMultipleConversionsPerVisitor=allow_multiple_conversions,
            modifiers=modifiers,
        )
        runner = MarketingAnalyticsAttributionQueryRunner(query=query, team=self.team)
        runner.config.live_session_resolution_enabled = live_resolution
        response = runner.calculate()
        rows = {
            row.breakdownValue: _AttributionCounts(visitors=row.visitors, conversions=row.influencedConversions)
            for row in (response.results or [])
        }
        return rows, runner._live_session_resolution_used

    @parameterized.expand(
        [
            ("campaign", MarketingAnalyticsAttributionBreakdown.CAMPAIGN),
            ("channel", MarketingAnalyticsAttributionBreakdown.CHANNEL),
            ("source", MarketingAnalyticsAttributionBreakdown.SOURCE),
            ("medium", MarketingAnalyticsAttributionBreakdown.MEDIUM),
            ("term", MarketingAnalyticsAttributionBreakdown.TERM),
            ("content", MarketingAnalyticsAttributionBreakdown.CONTENT),
            ("referrer", MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN),
            ("landing_page", MarketingAnalyticsAttributionBreakdown.LANDING_PAGE),
        ]
    )
    def test_session_open_before_the_window_with_events_inside_it_counts_in_both_paths(
        self, _name: str, breakdown: MarketingAnalyticsAttributionBreakdown
    ) -> None:
        create_person(team=self.team, distinct_ids=["straddler"])
        before_window_minutes = (
            30
            if breakdown
            in (MarketingAnalyticsAttributionBreakdown.CAMPAIGN, MarketingAnalyticsAttributionBreakdown.CHANNEL)
            else 48 * 60
        )
        self._session(
            "straddler",
            WINDOW_START - timedelta(minutes=before_window_minutes),
            campaign="straddle",
            event_offsets_minutes=[0, before_window_minutes + 30],
            source="google",
        )
        self._conversion("straddler", datetime(2023, 1, 12, 12, 0, tzinfo=UTC))

        create_person(team=self.team, distinct_ids=["inside"])
        self._session(
            "inside",
            datetime(2023, 1, 11, 9, 0, tzinfo=UTC),
            campaign="inside",
            event_offsets_minutes=[0, 15],
            source="google",
        )
        self._conversion("inside", datetime(2023, 1, 12, 12, 0, tzinfo=UTC))
        flush_persons_and_events()

        live, live_used = self._run(breakdown, live_resolution=False)
        shared, shared_used = self._run(breakdown, live_resolution=True)

        assert not live_used
        assert shared_used, "shared live session resolution was not used"
        assert shared == live, f"shared={shared} legacy={live}"

    # Both paths hold their own reference to the ceiling, so both have to be lowered for the fixture
    # to stay small enough to read.
    @parameterized.expand([("repeat", True), ("first_only", False)])
    @patch("products.marketing_analytics.backend.hogql_queries.attribution_base.MAX_CONVERSIONS_PER_PERSON", 2)
    @patch("products.marketing_analytics.backend.hogql_queries.attribution_sessions_read.MAX_CONVERSIONS_PER_PERSON", 2)
    def test_a_person_over_the_conversion_ceiling_is_attributed_the_same_on_both_paths(
        self, _name: str, allow_multiple_conversions: bool
    ) -> None:
        create_person(team=self.team, distinct_ids=["heavy"])
        self._session("heavy", datetime(2023, 1, 11, 9, 0, tzinfo=UTC), campaign="heavy", event_offsets_minutes=[0])
        for hour in (10, 11, 12):
            self._conversion("heavy", datetime(2023, 1, 12, hour, 0, tzinfo=UTC))
        flush_persons_and_events()

        live, live_used = self._run(
            MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
            live_resolution=False,
            allow_multiple_conversions=allow_multiple_conversions,
        )
        shared, shared_used = self._run(
            MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
            live_resolution=True,
            allow_multiple_conversions=allow_multiple_conversions,
        )

        assert not live_used
        assert shared_used, "shared live session resolution was not used"
        assert shared == live, f"shared={shared} legacy={live}"

    def test_a_test_account_filter_falls_back_to_the_live_scan(self) -> None:
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

        live, live_used = self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, live_resolution=False)
        shared, shared_used = self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, live_resolution=True)

        # Pinned, so the fixture proves the internal person was dropped rather than never seeded.
        assert live == {"google": _AttributionCounts(visitors=1, conversions=1)}, live
        assert not shared_used, "shared resolution answered a query whose filter it cannot honor"
        assert shared == live, f"shared={shared} legacy={live}"

    @parameterized.expand([("direct", True, False), ("unattributed", False, True)])
    def test_exclusions_match_legacy_resolution(
        self, _name: str, exclude_direct: bool, exclude_unattributed: bool
    ) -> None:
        create_person(team=self.team, distinct_ids=["excluded-visitor"])
        self._session("excluded-visitor", datetime(2023, 1, 11, 9, tzinfo=UTC), campaign="", event_offsets_minutes=[0])
        self._conversion("excluded-visitor", datetime(2023, 1, 12, 12, tzinfo=UTC))
        flush_persons_and_events()
        included, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, live_resolution=True)
        assert used
        assert included == {"": _AttributionCounts(visitors=1, conversions=1)}
        for shared in (False, True):
            rows, used = self._run(
                MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
                live_resolution=shared,
                exclude_direct=exclude_direct,
                exclude_unattributed=exclude_unattributed,
            )
            assert used is shared
            assert rows == {}

    @parameterized.expand(
        [
            (version, before_hours)
            for version in (SessionTableVersion.V2, SessionTableVersion.V3)
            for before_hours in (48, 120)
        ]
    )
    def test_session_starting_before_reachback_preserves_reach(
        self, version: SessionTableVersion, before_hours: int
    ) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        create_person(team=self.team, distinct_ids=["long-session"])
        self._session(
            "long-session",
            WINDOW_START - timedelta(hours=before_hours),
            campaign="long",
            event_offsets_minutes=[0, (before_hours + 1) * 60],
        )
        self._conversion("long-session", datetime(2023, 1, 12, 12, tzinfo=UTC))
        create_person(team=self.team, distinct_ids=["short-session"])
        self._session(
            "short-session", datetime(2023, 1, 11, 9, tzinfo=UTC), campaign="short", event_offsets_minutes=[0, 10]
        )
        self._conversion("short-session", datetime(2023, 1, 12, 12, tzinfo=UTC))
        flush_persons_and_events()
        live, _ = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, live_resolution=False)
        shared, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, live_resolution=True)
        assert used
        assert live.get("long") == (_AttributionCounts(visitors=1, conversions=0) if before_hours == 48 else None)
        assert live.get("short") == _AttributionCounts(visitors=1, conversions=1)
        assert shared == live

    @parameterized.expand([(version,) for version in (SessionTableVersion.V2, SessionTableVersion.V3)])
    def test_custom_channels_and_rule_changes_match_legacy_resolution(self, version: SessionTableVersion) -> None:
        self.team.modifiers = {
            "sessionTableVersion": version,
            "customChannelTypeRules": [
                {
                    "id": "member-offer",
                    "channel_type": "Member offer",
                    "combiner": "AND",
                    "items": [{"id": "url-rule", "key": "url", "op": "icontains", "value": ["segment=members"]}],
                }
            ],
        }
        for name, duration_days in (("member-a", 0), ("member-b", 5)):
            create_person(team=self.team, distinct_ids=[name])
            opened_at = datetime(2023, 1, 7, 9, tzinfo=UTC)
            session_id_timestamp = opened_at + timedelta(days=duration_days / 2)
            session_id = str(uuid7(session_id_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")))
            for offset in (0, max(10, duration_days * 1440)):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=name,
                    timestamp=opened_at + timedelta(minutes=offset),
                    properties={
                        "$session_id": session_id,
                        "$current_url": "https://example.com/offers?segment=members",
                        "utm_source": "partner-network",
                        "utm_medium": "referral",
                    },
                )
            self._conversion(name, datetime(2023, 1, 10, 12, tzinfo=UTC))
        flush_persons_and_events()
        for channel in ("Member offer", "Member referral"):
            self.team.modifiers["customChannelTypeRules"][0]["channel_type"] = channel
            for query_type, runner_type in (
                (MarketingAnalyticsAttributionQuery, MarketingAnalyticsAttributionQueryRunner),
                (MarketingAnalyticsAttributionPathsQuery, MarketingAnalyticsAttributionPathsQueryRunner),
            ):
                responses = []
                for live_resolution in (False, True):
                    runner = runner_type(
                        query=query_type(
                            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                            breakdownBy=MarketingAnalyticsAttributionBreakdown.CHANNEL,
                            conversionGoalId=GOAL_ID,
                            properties=[],
                        ),
                        team=self.team,
                    )
                    runner.config.live_session_resolution_enabled = live_resolution
                    response = runner.calculate()
                    assert runner._live_session_resolution_used is live_resolution
                    assert response.results
                    responses.append(response.results)
                    if isinstance(response, MarketingAnalyticsAttributionQueryResponse):
                        assert response.totalConversions == 2
                        assert response.unattributedConversions == 0
                        assert {row.breakdownValue for row in response.results} == {channel}
                    else:
                        assert response.attributedConversions == 2
                self.assertCountEqual(responses[0], responses[1])

    @parameterized.expand([(SessionTableVersion.V2,), (SessionTableVersion.V3,)])
    def test_long_session_growth_matches_legacy_dimensions(self, version: SessionTableVersion) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        create_person(team=self.team, distinct_ids=["growing-session"])
        session_id = str(uuid7("2023-01-07T09:00:00Z"))
        _create_event(
            team=self.team,
            distinct_id="growing-session",
            event="$pageview",
            timestamp="2023-01-07T09:00:00Z",
            properties={"$session_id": session_id, "$current_url": "https://example.com/"},
        )
        self._conversion("growing-session", datetime(2023, 1, 10, 12, tzinfo=UTC))
        _create_event(
            team=self.team,
            distinct_id="growing-session",
            event="$pageview",
            timestamp="2023-01-26T09:00:00Z",
            properties={
                "$session_id": session_id,
                "$current_url": "https://example.com/",
                "utm_campaign": "late-campaign",
            },
        )
        live, _ = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, live_resolution=False)
        shared, used = self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, live_resolution=True)
        assert used
        assert shared == live
        expected_campaign = "late-campaign" if version == SessionTableVersion.V3 else ""
        assert shared == {expected_campaign: _AttributionCounts(visitors=1, conversions=1)}

    @parameterized.expand(
        [
            (state, version)
            for state in ("merged", "override_first", "mapping_first", "split", "squashed")
            for version in (SessionTableVersion.V2, SessionTableVersion.V3)
        ]
    )
    def test_live_dimensions_follow_current_event_identity(self, state: str, version: SessionTableVersion) -> None:
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
                squashed_tables = ["sharded_events"]
                if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                    squashed_tables.append("sharded_events_json")
                for table in squashed_tables:
                    sync_execute(
                        f"ALTER TABLE {table} UPDATE person_id = %(person)s "
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
            for live_resolution in (False, True):
                runner = runner_type(query=query_type(**query_args), team=self.team)
                runner.config.live_session_resolution_enabled = live_resolution
                response = runner.calculate()
                self.assertEqual(runner._live_session_resolution_used, live_resolution)
                responses.append(response.results)
                if isinstance(response, MarketingAnalyticsAttributionQueryResponse):
                    self.assertEqual(response.totalConversions, 1)
                    self.assertEqual(response.unattributedConversions, 1 if state == "mapping_first" else 0)
                else:
                    self.assertEqual(response.attributedConversions, 0 if state == "mapping_first" else 1)
            self.assertCountEqual(responses[0], responses[1])

    @parameterized.expand(
        [
            (SessionTableVersion.V2, SessionTableVersion.V3, False, "google"),
            (SessionTableVersion.V3, SessionTableVersion.V2, False, "old"),
            (SessionTableVersion.AUTO, SessionTableVersion.V2, True, "old"),
            (SessionTableVersion.V2, SessionTableVersion.AUTO, True, "old"),
            (SessionTableVersion.V3, SessionTableVersion.V3, True, "google"),
        ]
    )
    def test_query_session_version_matches_live_dimensions(
        self, team_version: SessionTableVersion, query_version: SessionTableVersion, expected_shared: bool, source: str
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
        modifiers = HogQLQueryModifiers(sessionTableVersion=query_version)
        live, _ = self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, live_resolution=False, modifiers=modifiers)
        shared, used = self._run(
            MarketingAnalyticsAttributionBreakdown.SOURCE, live_resolution=True, modifiers=modifiers
        )
        assert used is expected_shared
        assert shared == live == {source: _AttributionCounts(visitors=1, conversions=1)}

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
        for query_type, runner_type in (
            (MarketingAnalyticsAttributionQuery, MarketingAnalyticsAttributionQueryRunner),
            (MarketingAnalyticsAttributionPathsQuery, MarketingAnalyticsAttributionPathsQueryRunner),
        ):
            responses = []
            for live_resolution in (False, True):
                runner = runner_type(
                    query=query_type(
                        dateRange=date_range,
                        breakdownBy=MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
                        conversionGoalId=GOAL_ID,
                        properties=[],
                    ),
                    team=self.team,
                )
                runner.config.live_session_resolution_enabled = live_resolution
                response = runner.calculate()
                assert not runner._live_session_resolution_used
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
            for live_resolution in (False, True):
                query = query_type(
                    dateRange=date_range,
                    breakdownBy=MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
                    conversionGoalId=GOAL_ID,
                    properties=[],
                )
                runner = runner_type(query=query, team=self.team)
                runner.config.live_session_resolution_enabled = live_resolution
                response = runner.calculate()
                assert runner._live_session_resolution_used is live_resolution
                assert response.totalConversions == expected_conversions
                if isinstance(response, MarketingAnalyticsAttributionQueryResponse):
                    assert response.unattributedConversions == 0
                    rows = {row.breakdownValue: row.visitors for row in response.results or []}
                    assert rows == {"reach-only": 1, "boundary": 1, "start": 1}, (live_resolution, rows)
                else:
                    assert response.attributedConversions == expected_conversions
                results.append(response.results)
            self.assertCountEqual(results[0], results[1])

    def _assert_shared_live_parity(
        self, date_range: DateRange, *, campaigns: set[str], total_conversions: int, attributed_conversions: int
    ) -> None:
        for query_type, runner_type in (
            (MarketingAnalyticsAttributionQuery, MarketingAnalyticsAttributionQueryRunner),
            (MarketingAnalyticsAttributionPathsQuery, MarketingAnalyticsAttributionPathsQueryRunner),
        ):
            results = []
            for shared in (False, True):
                runner = runner_type(
                    query=query_type(
                        dateRange=date_range,
                        breakdownBy=MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
                        conversionGoalId=GOAL_ID,
                        properties=[],
                    ),
                    team=self.team,
                )
                runner.config.live_session_resolution_enabled = shared
                response = runner.calculate()
                assert runner._live_session_resolution_used is shared
                assert response.totalConversions == total_conversions
                if isinstance(response, MarketingAnalyticsAttributionQueryResponse):
                    assert {row.breakdownValue for row in response.results or []} == campaigns
                    assert response.unattributedConversions == total_conversions - attributed_conversions
                else:
                    assert response.attributedConversions == attributed_conversions
                results.append(response.results)
            self.assertCountEqual(results[0], results[1])

    @parameterized.expand(
        [
            (version, tz)
            for version in (SessionTableVersion.V2, SessionTableVersion.V3)
            for tz in ("UTC", "America/Los_Angeles")
        ]
    )
    def test_shared_live_resolution_crosses_midnight_without_cached_jobs(
        self, version: SessionTableVersion, boundary_timezone: str
    ) -> None:
        self.team.timezone = "America/Los_Angeles"
        self.team.modifiers = {"sessionTableVersion": version}
        boundary = datetime(2023, 1, 13, tzinfo=ZoneInfo(boundary_timezone)).astimezone(UTC)
        create_person(team=self.team, distinct_ids=["before-midnight", "after-midnight"])
        with time_machine.travel(boundary - timedelta(minutes=1), tick=False) as clock:
            self._session(
                "before-midnight", boundary - timedelta(minutes=3), campaign="before", event_offsets_minutes=[0]
            )
            self._conversion("before-midnight", boundary - timedelta(minutes=2))
            flush_persons_and_events()
            self._assert_shared_live_parity(
                DateRange(date_from="-7d"), campaigns={"before"}, total_conversions=1, attributed_conversions=1
            )
            clock.shift(timedelta(minutes=3))
            self._session(
                "after-midnight", boundary + timedelta(seconds=30), campaign="after", event_offsets_minutes=[0]
            )
            self._conversion("after-midnight", boundary + timedelta(minutes=1))
            flush_persons_and_events()
            self._assert_shared_live_parity(
                DateRange(date_from="-7d"), campaigns={"before", "after"}, total_conversions=2, attributed_conversions=2
            )
        assert not PreaggregationJob.objects.filter(team=self.team).exists()

    def test_shared_live_resolution_reads_delayed_nullable_campaign(self) -> None:
        self.team.modifiers = {"sessionTableVersion": SessionTableVersion.V3}
        create_person(team=self.team, distinct_ids=["visitor"])
        opened_at = datetime(2023, 1, 11, 9, tzinfo=UTC)
        session_id = uuid7("2023-01-11T09:00:00Z")
        _create_event(
            team=self.team,
            distinct_id="visitor",
            event="$pageview",
            timestamp=opened_at,
            properties={"$session_id": str(session_id), "$current_url": "https://example.com/"},
        )
        self._conversion("visitor", opened_at + timedelta(hours=1))
        flush_persons_and_events()
        sync_execute(
            """
            INSERT INTO raw_sessions_v3
                (team_id, session_id_v7, min_timestamp, max_timestamp, max_inserted_at, entry_utm_campaign)
            SELECT %(team)s, toUInt128(%(session)s),
                toDateTime64('2023-01-11 09:05:00', 6, 'UTC'),
                toDateTime64('2023-01-11 09:05:00', 6, 'UTC'),
                toDateTime64('2023-01-11 09:05:00', 6, 'UTC'),
                initializeAggregation('argMinState', toNullable('delayed'), toDateTime64('2023-01-11 09:05:00', 6, 'UTC'))
            SETTINGS insert_distributed_sync=1
            """,
            {"team": self.team.pk, "session": str(session_id.int)},
        )
        self._assert_shared_live_parity(
            DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            campaigns={"delayed"},
            total_conversions=1,
            attributed_conversions=1,
        )

    @parameterized.expand([(SessionTableVersion.V2,), (SessionTableVersion.V3,)])
    def test_shared_live_resolution_preserves_independent_session_and_event_bounds(
        self, version: SessionTableVersion
    ) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        normal_pageview = datetime(2023, 1, 11, 9, tzinfo=UTC)
        before_credit_bound = datetime(2023, 1, 8, 11, 59, 59, tzinfo=UTC)
        later_raw_start = datetime(2023, 1, 8, 12, 0, 1, tzinfo=UTC)
        scenarios = [
            ("raw-before-range", normal_pageview, [0], datetime(2023, 1, 5, 23, tzinfo=UTC)),
            ("raw-after-range", normal_pageview, [0], datetime(2023, 1, 21, 12, tzinfo=UTC)),
            ("raw-epoch", normal_pageview, [0], datetime(1970, 1, 1, tzinfo=UTC)),
            ("pageview-before-credit-bound", before_credit_bound, [0], later_raw_start),
            ("later-pageview-meets-credit-bound", before_credit_bound, [0, 1], later_raw_start),
            ("raw-absent", normal_pageview, [0], None),
        ]
        session_ids = {}
        for campaign, pageview_at, offsets, _ in scenarios:
            create_person(team=self.team, distinct_ids=[campaign])
            session_ids[campaign] = self._session(
                campaign, pageview_at, campaign=campaign, event_offsets_minutes=offsets
            )
            self._conversion(campaign, datetime(2023, 1, 12, 12, tzinfo=UTC))
        flush_persons_and_events()
        table = escape_clickhouse_identifier(
            "sharded_raw_sessions_v3" if version == SessionTableVersion.V3 else "sharded_raw_sessions"
        )
        for campaign, _, _, raw_at in scenarios:
            parameters = {"team": self.team.pk, "session": str(session_ids[campaign].int)}
            if raw_at is None:
                sync_execute(
                    f"ALTER TABLE {table} DELETE WHERE team_id = %(team)s AND session_id_v7 = toUInt128(%(session)s) SETTINGS mutations_sync = 2",
                    parameters,
                )
            else:
                sync_execute(
                    f"ALTER TABLE {table} UPDATE min_timestamp = toDateTime64(%(timestamp)s, 6, 'UTC'), "
                    "max_timestamp = toDateTime64(%(timestamp)s, 6, 'UTC') "
                    "WHERE team_id = %(team)s AND session_id_v7 = toUInt128(%(session)s) SETTINGS mutations_sync = 2",
                    {**parameters, "timestamp": raw_at.strftime("%Y-%m-%d %H:%M:%S.%f")},
                )
        self._assert_shared_live_parity(
            DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            campaigns={
                "raw-before-range",
                "raw-after-range",
                "pageview-before-credit-bound",
                "later-pageview-meets-credit-bound",
            },
            total_conversions=len(scenarios),
            attributed_conversions=1,
        )

    def test_shared_live_resolution_preserves_session_filtered_conversion_goals(self) -> None:
        config = self.team.marketing_analytics_config
        config.conversion_goals[0]["properties"] = [
            {"type": "session", "key": "$entry_utm_source", "operator": "exact", "value": ["google"]}
        ]
        config.save()
        create_person(team=self.team, distinct_ids=["visitor"])
        for at, conversion_at, campaign in (
            (datetime(2023, 1, 6, 9, tzinfo=UTC), datetime(2023, 1, 13, 10, tzinfo=UTC), "older-id"),
            (datetime(2023, 1, 12, 9, tzinfo=UTC), datetime(2023, 1, 12, 10, tzinfo=UTC), "recent-id"),
        ):
            session_id = self._session("visitor", at, campaign=campaign, event_offsets_minutes=[0], source="google")
            _create_event(
                team=self.team,
                distinct_id="visitor",
                event=CONVERSION_EVENT,
                timestamp=conversion_at,
                properties={"$session_id": str(session_id), "revenue": 100},
            )
        flush_persons_and_events()
        for query_type, runner_type in (
            (MarketingAnalyticsAttributionQuery, MarketingAnalyticsAttributionQueryRunner),
            (MarketingAnalyticsAttributionPathsQuery, MarketingAnalyticsAttributionPathsQueryRunner),
        ):
            responses = []
            for shared in (False, True):
                runner = runner_type(
                    query=query_type(
                        dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                        breakdownBy=MarketingAnalyticsAttributionBreakdown.CAMPAIGN,
                        conversionGoalId=GOAL_ID,
                        properties=[],
                        allowMultipleConversionsPerVisitor=True,
                    ),
                    team=self.team,
                )
                runner.config.live_session_resolution_enabled = shared
                response = runner.calculate()
                assert response.totalConversions == 2
                assert not runner._live_session_resolution_used
                responses.append(response.results)
            self.assertCountEqual(responses[0], responses[1])
