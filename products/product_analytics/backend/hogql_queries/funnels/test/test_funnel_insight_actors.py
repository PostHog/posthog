from typing import Any, Optional, cast

import time_machine
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    ActorsQuery,
    EventsNode,
    EventsQuery,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelsQuery,
    HogQLQueryModifiers,
    InsightActorsQuery,
    InsightActorsQueryOptions,
    PersonsOnEventsMode,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.actor_strategies import SessionStrategy
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.insight_actors_query_options_runner import InsightActorsQueryOptionsRunner
from posthog.hogql_queries.insight_actors_query_runner import InsightActorsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner, get_query_runner_or_none
from posthog.models import Organization, Team, User
from posthog.models.group.util import create_group
from posthog.models.instance_setting import override_instance_config
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner


class TestFunnelInsightActors(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_test_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "org1"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:2",
            properties={"name": "org2"},
        )

    def _create_events(self, data, event="$pageview"):
        for id, timestamps in data:
            with time_machine.travel(timestamps[0], tick=False):
                _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[id],
                    properties={
                        "name": id,
                        **({"email": "test@posthog.com"} if id == "p1" else {}),
                    },
                )
            for timestamp in timestamps:
                _create_event(
                    team=self.team, event=event, distinct_id=id, timestamp=timestamp, properties={"$group_0": "org:1"}
                )

    def _create_test_events(self):
        self._create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

    def select(self, query: str, placeholders: Optional[dict[str, Any]] = None, modifiers: Optional[dict] = None):
        if placeholders is None:
            placeholders = {}
        return execute_hogql_query(
            query=query,
            team=self.team,
            placeholders=placeholders,
            modifiers=HogQLQueryModifiers(**modifiers) if modifiers else None,
        )

    @snapshot_clickhouse_queries
    def test_insight_persons_funnels_query(self):
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
                select * from (
                    <ActorsQuery select={['properties.name']}>
                        <FunnelsActorsQuery funnelStep={2}>
                            <FunnelsQuery
                                dateRange={<DateRange date_from='2020-01-01' date_to='2020-01-19' />}
                                series={[<EventsNode event='$pageview' />, <EventsNode event='$pageview' />]}
                            />
                        </FunnelsActorsQuery>
                    </ActorsQuery>
                )
                """
        )

        self.assertEqual([("p1",), ("p2",)], response.results)

    def test_insight_groups_funnels_query(self):
        self._create_test_groups()
        self._create_test_events()
        self.team.timezone = "US/Pacific"
        self.team.save()

        response = self.select(
            """
                select * from (
                    <ActorsQuery select={['properties.name']}>
                        <FunnelsActorsQuery funnelStep={2}>
                            <FunnelsQuery
                                aggregation_group_type_index={0}
                                dateRange={<DateRange date_from='2020-01-01' date_to='2020-01-19' />}
                                series={[<EventsNode event='$pageview' />, <EventsNode event='$pageview' />]}
                            />
                        </FunnelsActorsQuery>
                    </ActorsQuery>
                )
                """
        )

        self.assertEqual(
            [
                ("org1",),
            ],
            response.results,
        )


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
class TestNativeEventsActorRouting(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=44, modifiers={}, organization=Organization(id=1))
        self.user = User(id=123, is_staff=True, is_active=True)
        self.modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
        self.enterContext(
            patch(
                "posthog.models.event.new_events_schema.get_instance_setting",
                side_effect={
                    "CLICKHOUSE_NATIVE_EVENTS_TEAMS": [44],
                    "CLICKHOUSE_NATIVE_EVENTS_HOST": "native.example.com",
                }.get,
            )
        )
        self.enterContext(
            patch(
                "products.web_analytics.backend.hogql_queries.cookieless_flag.resolve_cookieless_traffic_is_regular_modifier",
                return_value=True,
            )
        )

    @parameterized.expand(
        [(kind, True, None) for kind in ("InsightActorsQuery", "InsightActorsQueryOptions", "ActorsQuery")]
        + [(kind, True, False) for kind in ("InsightActorsQuery", "ActorsQuery")]
        + [(kind, None, True) for kind in ("InsightActorsQuery", "ActorsQuery")]
        + [(kind, None, None) for kind in ("InsightActorsQuery", "ActorsQuery")]
        + [("EventsQuery", choice, None) for choice in (None, False, True)]
    )
    def test_actor_queries_inherit_the_source_route_unless_explicitly_overridden(
        self, kind: str, source_choice: bool | None, wrapper_choice: bool | None
    ) -> None:
        modifiers = self.modifiers.model_copy(update={"useNewEventsCluster": source_choice})
        source = FunnelsQuery(series=[EventsNode(event="example"), EventsNode(event="finished")], modifiers=modifiers)
        actors = FunnelsActorsQuery(source=source, funnelStep=1)
        query: BaseModel
        if kind == "InsightActorsQuery":
            query = InsightActorsQuery(source=source, modifiers=HogQLQueryModifiers())
        elif kind == "ActorsQuery":
            query = ActorsQuery(source=actors, modifiers=HogQLQueryModifiers())
        elif kind == "InsightActorsQueryOptions":
            query = InsightActorsQueryOptions(source=actors)
        else:
            source.modifiers = (
                modifiers.model_copy(update={"convertToProjectTimezone": True}) if source_choice is not None else None
            )
            self.team.timezone = "Europe/Amsterdam"
            query = EventsQuery(
                select=["timestamp"],
                source=InsightActorsQuery(source=source),
                modifiers=self.modifiers.model_copy(update={"convertToProjectTimezone": False}),
            )
        if wrapper_choice is not None:
            assert isinstance(query, (ActorsQuery, InsightActorsQuery))
            query.modifiers = self.modifiers.model_copy(
                update={"useNewEventsSchema": wrapper_choice, "useNewEventsCluster": wrapper_choice}
            )
        original = query.model_dump()
        runner = get_query_runner(query, self.team, user=self.user)
        native = source_choice if wrapper_choice is None else wrapper_choice
        self.assertEqual(runner.modifiers.personsOnEventsMode, PersonsOnEventsMode.DISABLED)
        self.assertIs(bool(runner.modifiers.useNewEventsSchema), bool(native))
        self.assertIs(runner.modifiers.useNewEventsCluster, native)
        if kind == "EventsQuery":
            self.assertIs(runner.modifiers.convertToProjectTimezone, False)
        self.assertEqual(query.model_dump(), original)


class TestActorExecutionUserContext(APIBaseTest):
    def test_insight_actors_runner_builds_from_a_dict(self) -> None:
        source = FunnelsQuery(series=[EventsNode(event="example"), EventsNode(event="finished")])
        runner = get_query_runner(InsightActorsQuery(source=source).model_dump(), self.team, user=self.user)
        self.assertIsInstance(runner.query, InsightActorsQuery)

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_session_actors_hydrate_on_the_selected_cluster(self) -> None:
        source = FunnelsQuery(
            series=[EventsNode(event="started"), EventsNode(event="finished")],
            funnelsFilter=FunnelsFilter(funnelAggregateByHogQL="properties.$session_id"),
            modifiers=HogQLQueryModifiers(useNewEventsSchema=True, useNewEventsCluster=True),
        )
        with (
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"),
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk]),
            patch("posthog.hogql.query.sync_execute", return_value=([], [])) as execute,
        ):
            runner = get_query_runner(ActorsQuery(source=FunnelsActorsQuery(source=source, funnelStep=1)), self.team)
            assert isinstance(runner, ActorsQueryRunner) and isinstance(runner.strategy, SessionStrategy)
            runner.strategy.get_actors(["a-session"])
        self.assertEqual(execute.call_args.kwargs["workload"], Workload.NEW_EVENTS_CLUSTER)

    @parameterized.expand([("ActorsQuery",), ("InsightActorsQuery",), ("InsightActorsQueryOptions",), ("EventsQuery",)])
    def test_nested_query_context_follows_execution_user(self, kind: str) -> None:
        source = FunnelsQuery(series=[EventsNode(event="started"), EventsNode(event="finished")])
        actors = FunnelsActorsQuery(source=source, funnelStep=1)
        queries = {
            "ActorsQuery": ActorsQuery(source=actors),
            "InsightActorsQuery": InsightActorsQuery(source=source),
            "InsightActorsQueryOptions": InsightActorsQueryOptions(source=actors),
            "EventsQuery": EventsQuery(select=["*"], source=InsightActorsQuery(source=source)),
        }
        runner = get_query_runner_or_none(query=queries[kind], team=self.team, user=self.user)
        assert runner is not None

        def source_runner() -> QueryRunner:
            if isinstance(runner, ActorsQueryRunner):
                assert runner.source_query_runner is not None
                return runner.source_query_runner
            assert isinstance(runner, (InsightActorsQueryRunner, InsightActorsQueryOptionsRunner, EventsQueryRunner))
            return runner.source_runner

        def execution_context() -> HogQLContext:
            child = source_runner()
            if isinstance(runner, ActorsQueryRunner):
                return child.build_hogql_context()
            if isinstance(runner, EventsQueryRunner):
                child = cast(InsightActorsQueryRunner, child).source_runner
            return cast(FunnelsQueryRunner, child).context.hogql_context

        child = source_runner()
        assert execution_context().user is self.user
        other_user = User.objects.create_and_join(self.organization, "context-user@example.com", None)
        runner.set_user(other_user)
        assert source_runner() is child
        assert execution_context().user is other_user
