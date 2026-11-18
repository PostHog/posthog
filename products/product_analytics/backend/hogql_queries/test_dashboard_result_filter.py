import json
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    ActorsQuery,
    Breakdown,
    BreakdownFilter,
    CachedTrendsQueryResponse,
    CacheMissResponse,
    DataWarehouseNode,
    EventsNode,
    HogQLPropertyFilter,
    HogQLQuery,
    InsightActorsQuery,
    TrendsQuery,
)

from posthog.hogql.escape_sql import escape_hogql_string

from posthog.constants import AvailableFeature
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.query_cache import QueryCache
from posthog.query_cache.storage import delete_entry
from posthog.test.persons import create_group_type_mapping, create_person
from posthog.uuidt import uuid7

from products.access_control.backend.models.access_control import AccessControl
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner


class TestDashboardResultFilter(ClickhouseTestMixin, BaseTest):
    def test_matches_insight_filters_funnel_sessions_instead_of_every_session_for_a_person(self) -> None:
        selected_session = str(uuid7())
        other_session = str(uuid7())
        person = create_person(team=self.team, distinct_ids=["session-example"])
        for event, session, timestamp in [
            ("signup", selected_session, "2026-01-02T10:00:00Z"),
            ("purchase", selected_session, "2026-01-02T10:05:00Z"),
            ("purchase", other_session, "2026-01-03T10:00:00Z"),
        ]:
            _create_event(
                team=self.team,
                distinct_id="session-example",
                person_id=person.uuid,
                event=event,
                timestamp=timestamp,
                properties={"$session_id": session},
            )
        flush_persons_and_events()
        selection = {
            "kind": "ActorsQuery",
            "source": {
                "kind": "FunnelsActorsQuery",
                "funnelStep": 1,
                "source": {
                    "kind": "FunnelsQuery",
                    "series": [{"kind": "EventsNode", "event": "signup"}, {"kind": "EventsNode", "event": "purchase"}],
                    "dateRange": {"date_from": "2026-01-01", "date_to": "2026-01-04"},
                    "funnelsFilter": {"funnelAggregateByHogQL": "properties.$session_id"},
                },
            },
        }
        result = HogQLQueryRunner(
            query=HogQLQuery(
                query="SELECT count() FROM events WHERE event = 'purchase' AND matchesInsight("
                + escape_hogql_string(json.dumps(selection))
                + ")"
            ),
            team=self.team,
        ).calculate()
        self.assertEqual(result.results, [(1,)])

    @parameterized.expand([("people", None), ("groups", 0)])
    def test_matches_insight_filters_by_complete_population_and_selected_breakdown(
        self, _name: str, group_index: int | None
    ) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        if group_index is not None:
            create_group_type_mapping(team=self.team, group_type_index=group_index, group_type="company")
        for index in range(103):
            distinct_id = f"selection-user-{index}"
            person = create_person(team=self.team, distinct_ids=[distinct_id])
            _create_event(
                team=self.team,
                distinct_id=distinct_id,
                event="purchase",
                timestamp="2026-01-03T12:00:00Z",
                properties={"$group_0": f"company-{index}"},
            )
            _create_event(
                team=self.team if index < 102 else other_team,
                distinct_id=distinct_id,
                person_id=person.uuid,
                event="signup",
                timestamp="2026-01-02T12:00:00Z",
                properties={"plan": "paid" if index != 101 else "free", "$group_0": f"company-{index}"},
            )
        if group_index is not None:
            _create_event(
                team=self.team,
                distinct_id="another-company-member",
                event="purchase",
                timestamp="2026-01-03T12:00:00Z",
                properties={"$group_0": "company-0"},
            )
        flush_persons_and_events()
        selection = {
            "kind": "ActorsQuery",
            "limit": 1,
            "offset": 100,
            "source": {
                "kind": "InsightActorsQuery",
                "day": "2026-01-02",
                "series": 0,
                "breakdown": ["paid"] if group_index is None else "paid",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "signup",
                            **(
                                {"math": "unique_group", "math_group_type_index": group_index}
                                if group_index is not None
                                else {}
                            ),
                        }
                    ],
                    "dateRange": {"date_from": "2026-01-01", "date_to": "2026-01-04"},
                    "breakdownFilter": {"breakdown": "plan", "breakdown_type": "event"},
                },
            },
        }
        result = HogQLQueryRunner(
            query=HogQLQuery(
                query="SELECT distinct_id FROM events e WHERE event = 'purchase' AND matchesInsight("
                + escape_hogql_string(json.dumps(selection))
                + ") ORDER BY distinct_id LIMIT 1000"
            ),
            team=self.team,
        ).calculate()
        expected = [(f"selection-user-{index}",) for index in range(101)]
        if group_index is not None:
            expected.append(("another-company-member",))
        self.assertEqual(result.results, sorted(expected))
        assert result.hogql is not None
        replayed = HogQLQueryRunner(query=HogQLQuery(query=result.hogql), team=self.team).calculate()
        self.assertEqual(replayed.results, result.results)


@pytest.mark.ee
class TestDashboardResultFilterCache(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    @parameterized.expand(
        [
            (kind, name)
            for kind in (
                "hogql",
                "trends",
                "actors",
                "metadata_breakdown",
                "metadata_breakdowns",
                "warehouse",
                "warehouse_id",
                "test_accounts",
                "actors_test_accounts",
                "saved_modifiers",
                "query_tag_test_accounts",
                "query_tag_properties",
            )
            for name in ("matchesInsight", r"`matches\0Insight`", r'"matches\0Insight"')
        ]
    )
    def test_insight_selection_partitions_cache_on_access_control(self, kind: str, name: str) -> None:
        source = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            properties=[HogQLPropertyFilter(key="person_id in (select id from system.notebooks)")],
        )
        selection = ActorsQuery(source=InsightActorsQuery(source=source))
        predicate = f"{name}({escape_hogql_string(selection.model_dump_json())})"
        target = TrendsQuery(series=[EventsNode(event="$pageview")], properties=[HogQLPropertyFilter(key=predicate)])
        if kind in ("metadata_breakdown", "metadata_breakdowns"):
            target.properties = []
            target.breakdownFilter = (
                BreakdownFilter(breakdown_type="event_metadata", breakdown=predicate)
                if kind == "metadata_breakdown"
                else BreakdownFilter(breakdowns=[Breakdown(type="event_metadata", property=predicate)])
            )
        elif kind in ("warehouse", "warehouse_id"):
            target.properties = []
            target.series = [
                DataWarehouseNode(
                    id="events",
                    table_name="events",
                    id_field=predicate if kind == "warehouse_id" else "uuid",
                    timestamp_field="timestamp",
                    distinct_id_field=predicate if kind == "warehouse" else "distinct_id",
                )
            ]
        elif kind in ("test_accounts", "actors_test_accounts", "query_tag_test_accounts"):
            target.properties = []
            target.filterTestAccounts = True
            self.team.test_account_filters = [{"type": "hogql", "key": predicate}]
            self.team.save()
        elif kind == "saved_modifiers":
            target.properties = []
            self.team.modifiers = {
                "dataWarehouseEventsModifiers": [
                    {
                        "table_name": "events",
                        "id_field": predicate,
                        "timestamp_field": "timestamp",
                        "distinct_id_field": "distinct_id",
                    }
                ]
            }
            self.team.save()
        query = (
            HogQLQuery(query=f"select count() from events where {predicate}")
            if kind == "hogql"
            else HogQLQuery(query="select count() from events")
            if kind == "saved_modifiers"
            else ActorsQuery(source=InsightActorsQuery(source=target))
            if kind in ("actors", "actors_test_accounts")
            else target
        )
        if kind.startswith("query_tag_"):
            attributes = " ".join(
                f"{key}={{{json.dumps(value)}}}"
                for key, value in target.model_dump(mode="json", exclude_none=True).items()
                if key != "kind"
            )
            query = HogQLQuery(query=f"select * from <TrendsQuery {attributes} />")
        runner_class = {
            "hogql": HogQLQueryRunner,
            "saved_modifiers": HogQLQueryRunner,
            "query_tag_test_accounts": HogQLQueryRunner,
            "query_tag_properties": HogQLQueryRunner,
            "actors": ActorsQueryRunner,
            "actors_test_accounts": ActorsQueryRunner,
        }.get(kind, TrendsQueryRunner)
        access = AccessControl.objects.create(team=self.team, resource="notebook", access_level="none")
        denied_runner = runner_class(query=query, team=self.team, user=self.user)
        assert "notebook" in denied_runner.get_cache_payload()["restricted_resources"]
        denied_key = denied_runner.get_cache_key()

        access.access_level = "editor"
        access.save()
        granted_key = runner_class(query=query, team=self.team, user=self.user).get_cache_key()
        assert denied_key != granted_key

    @time_machine.travel("2026-01-03T12:00:00Z", tick=False)
    def test_saved_test_account_selection_does_not_share_an_admin_cache_entry(self) -> None:
        source = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            properties=[HogQLPropertyFilter(key="event in (select title from system.notebooks)")],
        )
        selection = ActorsQuery(source=InsightActorsQuery(source=source))
        self.team.test_account_filters = [
            {"type": "hogql", "key": f"matchesInsight({escape_hogql_string(selection.model_dump_json())})"}
        ]
        self.team.save()
        query = TrendsQuery(series=[EventsNode(event="$pageview")], filterTestAccounts=True)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_runner = TrendsQueryRunner(query=query, team=self.team, user=self.user)
        admin_key = admin_runner.get_cache_key()
        self.addCleanup(delete_entry, admin_key)
        now = datetime.now(UTC)
        response = CachedTrendsQueryResponse(
            results=[],
            cache_key=admin_key,
            is_cached=False,
            last_refresh=now,
            next_allowed_client_refresh=now + timedelta(minutes=5),
            timezone=self.team.timezone,
        )
        assert QueryCache(team_id=self.team.pk, cache_key=admin_key).store_result(
            response=response.model_dump(), target_age=None
        )
        admin_response = admin_runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
        assert isinstance(admin_response, CachedTrendsQueryResponse) and admin_response.is_cached

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(team=self.team, resource="notebook", access_level="none")
        denied_runner = TrendsQueryRunner(query=query, team=self.team, user=self.user)
        assert isinstance(denied_runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE), CacheMissResponse)
