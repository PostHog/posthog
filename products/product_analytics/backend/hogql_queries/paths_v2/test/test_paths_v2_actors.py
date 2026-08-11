from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActorsQuery,
    DateRange,
    FunnelsActorsQuery,
    FunnelsQuery,
    PathsV2ActorsQuery,
    PathsV2Anchor,
    PathsV2AnchorType,
    PathsV2ElementSelector,
    PathsV2ElementType,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    PathsV2StepSource,
)

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.insight_actors_query_runner import InsightActorsQueryRunner
from posthog.models.person import Person
from posthog.test.test_journeys import journeys_for

from products.product_analytics.backend.hogql_queries.paths_v2.funnel_converter import (
    anchored_segment_to_funnels_query,
    edge_to_funnels_query,
)
from products.product_analytics.backend.hogql_queries.paths_v2.paths_v2_query_runner import PathsV2QueryRunner

DATE_RANGE = DateRange(date_from="2023-03-01", date_to="2023-03-31")


def _sources(*events: str) -> list[PathsV2StepSource]:
    return [PathsV2StepSource(event=event) for event in events]


def _timeline(
    distinct_id: str, *events: str, start: str = "2023-03-10 10:00:00", step_minutes: int = 5
) -> dict[str, list[dict[str, Any]]]:
    start_dt = datetime.fromisoformat(start)
    return {
        distinct_id: [
            {
                "event": event,
                "timestamp": (start_dt + timedelta(minutes=i * step_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for i, event in enumerate(events)
        ]
    }


def _item(event: str, label: str | None = None) -> PathsV2Item:
    return PathsV2Item(event=event, label=label)


def _node(step_index: int, item: PathsV2Item) -> PathsV2ElementSelector:
    return PathsV2ElementSelector(elementType=PathsV2ElementType.NODE, stepIndex=step_index, item=item)


def _other(step_index: int) -> PathsV2ElementSelector:
    return PathsV2ElementSelector(elementType=PathsV2ElementType.OTHER, stepIndex=step_index)


def _drop_off(step_index: int) -> PathsV2ElementSelector:
    return PathsV2ElementSelector(elementType=PathsV2ElementType.DROP_OFF, stepIndex=step_index)


def _edge(step_index: int, source: PathsV2Item | None, target: PathsV2Item | None) -> PathsV2ElementSelector:
    return PathsV2ElementSelector(
        elementType=PathsV2ElementType.EDGE, stepIndex=step_index, source=source, target=target
    )


def _any_step_edge(source: PathsV2Item, target: PathsV2Item) -> PathsV2ElementSelector:
    return PathsV2ElementSelector(elementType=PathsV2ElementType.EDGE, anyStep=True, source=source, target=target)


def _chain(items: list[PathsV2Item]) -> PathsV2ElementSelector:
    return PathsV2ElementSelector(elementType=PathsV2ElementType.CHAIN, chain=items)


class PathsV2ActorsTestBase(ClickhouseTestMixin, APIBaseTest):
    persons: dict[str, Person] = {}

    def _names_for(self, query: PathsV2Query, element: PathsV2ElementSelector) -> set[str]:
        response = InsightActorsQueryRunner(
            query=PathsV2ActorsQuery(source=query, element=element), team=self.team
        ).calculate()
        assert response.results is not None
        names_by_uuid = {person.uuid: name for name, person in self.persons.items()}
        return {names_by_uuid[row[0]] for row in response.results}

    def _funnel_actor_names(self, funnels_query: FunnelsQuery, funnel_step: int) -> set[str]:
        actors_query = ActorsQuery(
            source=FunnelsActorsQuery(source=funnels_query, funnelStep=funnel_step), select=["id"]
        )
        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()
        names_by_uuid = {person.uuid: name for name, person in self.persons.items()}
        return {names_by_uuid[row[0]] for row in response.results}

    def _displayed_elements(self, query: PathsV2Query) -> tuple[dict[Any, float], dict[Any, set[str]]]:
        """Every element the grid displays, keyed the same way twice: the count shown on it, and the
        actor set its modal returns. Comparing the two dicts is the by-construction contract, with no
        expected numbers written down — it holds for any fixture, in either chart mode."""
        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results
        displayed_counts: dict[Any, float] = {}
        actor_sets: dict[Any, set[str]] = {}
        key: tuple[Any, ...]
        for step in results.steps:
            for row in step.rows:
                key = ("node", step.stepIndex, row.item.event)
                displayed_counts[key] = row.count
                actor_sets[key] = self._names_for(query, _node(step.stepIndex, row.item))
            if step.otherCount:
                key = ("other", step.stepIndex)
                displayed_counts[key] = step.otherCount
                actor_sets[key] = self._names_for(query, _other(step.stepIndex))
            if step.dropOffCount:
                key = ("dropOff", step.stepIndex)
                displayed_counts[key] = step.dropOffCount
                actor_sets[key] = self._names_for(query, _drop_off(step.stepIndex))
        for edge in results.edges:
            key = ("edge", edge.stepIndex, edge.source and edge.source.event, edge.target and edge.target.event)
            displayed_counts[key] = edge.count
            actor_sets[key] = self._names_for(query, _edge(edge.stepIndex, edge.source, edge.target))
        return displayed_counts, actor_sets


class TestPathsV2ActorsElements(PathsV2ActorsTestBase):
    maxDiff = None

    def test_open_mode_every_displayed_element_equals_its_actor_set(self):
        # A grid with named rows, a bucketed other row (e ties with d at step 2; d wins the
        # name-ascending tie-break), drop-offs at every column, edges into and out of the other
        # row, and one actor (p5) with two journeys to exercise per-element dedup.
        self.persons = journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "b", "c"),
                **_timeline("p2", "a", "b", "d"),
                **_timeline("p3", "a", "d", "c"),
                **_timeline("p4", "d"),
                "p5": [
                    *_timeline("p5", "a", "b")["p5"],
                    *_timeline("p5", "a", "e", "c", start="2023-03-10 14:00:00")["p5"],
                ],
            },
        )
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c", "d", "e"), maxSteps=3, maxRowsPerStep=2),
        )
        displayed_counts, actor_sets = self._displayed_elements(query)

        self.assertEqual(
            actor_sets,
            {
                ("node", 0, "a"): {"p1", "p2", "p3", "p5"},
                ("node", 0, "d"): {"p4"},
                ("node", 1, "b"): {"p1", "p2", "p5"},
                ("node", 1, "d"): {"p3"},
                ("other", 1): {"p5"},
                ("node", 2, "c"): {"p1", "p3", "p5"},
                ("node", 2, "d"): {"p2"},
                ("dropOff", 0): {"p4"},
                ("dropOff", 1): {"p5"},
                ("dropOff", 2): {"p1", "p2", "p3", "p5"},
                ("edge", 0, "a", "b"): {"p1", "p2", "p5"},
                ("edge", 0, "a", "d"): {"p3"},
                ("edge", 0, "a", None): {"p5"},
                ("edge", 1, "b", "c"): {"p1"},
                ("edge", 1, "b", "d"): {"p2"},
                ("edge", 1, "d", "c"): {"p3"},
                ("edge", 1, None, "c"): {"p5"},
            },
        )
        # Every modal equals the number on its element, for every element the grid displays.
        self.assertEqual(displayed_counts, {key: len(names) for key, names in actor_sets.items()})

    def test_edges_between_two_other_rows_equal_their_actor_sets(self):
        # With one named row per step, p3's journey runs other → other: the only positional-edge
        # shape where neither endpoint names a path item.
        self.persons = journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "b"),
                **_timeline("p2", "a", "b"),
                **_timeline("p3", "c", "d"),
            },
        )
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c", "d"), maxRowsPerStep=1),
        )

        displayed_counts, actor_sets = self._displayed_elements(query)

        self.assertEqual(actor_sets[("edge", 0, None, None)], {"p3"})
        self.assertEqual(displayed_counts, {key: len(names) for key, names in actor_sets.items()})

    def test_collapse_off_every_displayed_element_equals_its_actor_set(self):
        # Collapse off swaps the collapsed journeys for the raw ones in every aggregation stage, so
        # immediate repeats become their own steps. Count and actor set must move together.
        self.persons = journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "a", "b"),
                **_timeline("p2", "a", "b", "b"),
            },
        )
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b"), collapseRepeats=False),
        )

        displayed_counts, actor_sets = self._displayed_elements(query)

        self.assertGreater(len(displayed_counts), 4)
        self.assertEqual(displayed_counts, {key: len(names) for key, names in actor_sets.items()})

    def test_any_step_count_is_set_exactly_on_open_mode_named_edges(self):
        self.persons = journeys_for(
            team=self.team,
            events_by_person={**_timeline("p1", "a", "b"), **_timeline("p5", "a", "e", "c")},
        )
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c", "e"), maxRowsPerStep=1),
        )
        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results

        by_key = {
            (edge.stepIndex, edge.source and edge.source.event, edge.target and edge.target.event): edge
            for edge in results.edges
        }
        # a is the only named row at step 1; b and e tie at step 2 where b wins, bucketing e.
        self.assertEqual(by_key[(0, "a", "b")].anyStepCount, 1)
        self.assertIsNone(by_key[(0, "a", None)].anyStepCount)


class TestPathsV2EdgeContractActorSets(PathsV2ActorsTestBase):
    maxDiff = None

    def test_any_step_edge_set_equals_funnel_actor_set(self):
        # q3's a → b pair sits beyond the three-step display trim, so it is invisible to every
        # positional edge but must count for the any-step set: the converted funnel knows no trim.
        self.persons = journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("q1", "x", "a", "b"),
                **_timeline("q2", "a", "b"),
                **_timeline("q3", "w", "x", "a", "b"),
            },
        )
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("w", "x", "a", "b"), maxSteps=3),
        )
        source, target = _item("a"), _item("b")

        any_step_names = self._names_for(query, _any_step_edge(source, target))
        funnel_names = self._funnel_actor_names(edge_to_funnels_query(query, self.team, source, target), funnel_step=2)
        self.assertEqual(any_step_names, {"q1", "q2", "q3"})
        self.assertEqual(any_step_names, funnel_names)

        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results
        positional = {
            (edge.stepIndex,): self._names_for(query, _edge(edge.stepIndex, edge.source, edge.target))
            for edge in results.edges
            if edge.source == source and edge.target == target
        }
        self.assertEqual(positional, {(0,): {"q2"}, (1,): {"q1"}})
        for edge in results.edges:
            if edge.source == source and edge.target == target:
                self.assertEqual(edge.anyStepCount, 3)


class TestPathsV2AnchoredChainActorSets(PathsV2ActorsTestBase):
    maxDiff = None

    def _query(self) -> PathsV2Query:
        return PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(
                stepSources=_sources("home", "cart", "checkout", "browse"),
                anchor=PathsV2Anchor(type=PathsV2AnchorType.START, item=_item("home")),
            ),
        )

    def _seed(self) -> None:
        self.persons = journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("r1", "home", "cart", "checkout"),
                **_timeline("r2", "home", "cart"),
                **_timeline("r3", "home", "browse", "checkout"),
                **_timeline("r4", "browse", "checkout"),
            },
        )

    @parameterized.expand(
        [
            ("two_step_chain", ["home", "cart"], {"r1", "r2"}),
            ("three_step_chain", ["home", "cart", "checkout"], {"r1"}),
        ]
    )
    def test_chain_set_equals_prefix_count_and_funnel_actor_set(
        self, _name: str, chain_events: list[str], expected_names: set[str]
    ):
        self._seed()
        query = self._query()
        chain = [_item(event) for event in chain_events]

        chain_names = self._names_for(query, _chain(chain))
        self.assertEqual(chain_names, expected_names)

        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results
        prefix_counts = {tuple(item.event for item in prefix.items): prefix.count for prefix in results.prefixes}
        self.assertEqual(prefix_counts[tuple(chain_events)], len(chain_names))

        funnel_names = self._funnel_actor_names(
            anchored_segment_to_funnels_query(query, self.team, list(chain)), funnel_step=len(chain)
        )
        self.assertEqual(chain_names, funnel_names)

    def test_default_node_set_is_the_union_across_chains(self):
        # The default card shows the merged union count; the hovered chain narrows it. Both
        # states must resolve to their own displayed number's set.
        self._seed()
        query = self._query()

        union_names = self._names_for(query, _node(2, _item("checkout")))
        self.assertEqual(union_names, {"r1", "r3"})
        chain_names = self._names_for(query, _chain([_item("home"), _item("cart"), _item("checkout")]))
        self.assertEqual(chain_names, {"r1"})

    def test_anchored_edges_carry_no_any_step_count(self):
        self._seed()
        results = PathsV2QueryRunner(query=self._query(), team=self.team).calculate().results
        self.assertTrue(len(results.edges) > 0)
        self.assertEqual({edge.anyStepCount for edge in results.edges}, {None})

    @parameterized.expand(
        [("start_anchor", PathsV2AnchorType.START, "home"), ("end_anchor", PathsV2AnchorType.END, "checkout")]
    )
    def test_every_displayed_element_equals_its_actor_set(
        self, _name: str, anchor_type: PathsV2AnchorType, anchor_event: str
    ) -> None:
        # The open-mode contract, repeated for both anchor directions. An end anchor reverses each
        # actor's sequence, so step 0 is the anchor and the grid reads backward in time; the
        # modal-equals-count promise has to survive that reversal too.
        self._seed()
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(
                stepSources=_sources("home", "cart", "checkout", "browse"),
                anchor=PathsV2Anchor(type=anchor_type, item=_item(anchor_event)),
            ),
        )

        displayed_counts, actor_sets = self._displayed_elements(query)

        # Guards the equality below against silently passing on an empty grid
        self.assertGreater(len(displayed_counts), 4)
        self.assertEqual(displayed_counts, {key: len(names) for key, names in actor_sets.items()})

    def test_every_carried_prefix_equals_its_chain_actor_set(self):
        # Every carried prefix is a hover preview the user can land on, so each re-labelled card's
        # number must equal the set its click opens.
        self._seed()
        query = self._query()
        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results

        self.assertGreater(len(results.prefixes), 0)
        self.assertEqual(
            {tuple(item.event for item in prefix.items): prefix.count for prefix in results.prefixes},
            {
                tuple(item.event for item in prefix.items): len(self._names_for(query, _chain(list(prefix.items))))
                for prefix in results.prefixes
            },
        )


class TestPathsV2ActorsValidation(APIBaseTest):
    def _runner(self, anchored: bool = False) -> PathsV2QueryRunner:
        paths_filter = PathsV2Filter(stepSources=_sources("a", "b"))
        if anchored:
            paths_filter.anchor = PathsV2Anchor(type=PathsV2AnchorType.START, item=_item("a"))
        return PathsV2QueryRunner(query=PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=paths_filter), team=self.team)

    @parameterized.expand(
        [
            ("node_without_item", False, PathsV2ElementSelector(elementType=PathsV2ElementType.NODE, stepIndex=0)),
            (
                "node_without_step_index",
                False,
                PathsV2ElementSelector(elementType=PathsV2ElementType.NODE, item=_item("a")),
            ),
            ("other_without_step_index", False, PathsV2ElementSelector(elementType=PathsV2ElementType.OTHER)),
            ("drop_off_without_step_index", False, PathsV2ElementSelector(elementType=PathsV2ElementType.DROP_OFF)),
            (
                "positional_edge_without_step_index",
                False,
                PathsV2ElementSelector(elementType=PathsV2ElementType.EDGE, source=_item("a"), target=_item("b")),
            ),
            (
                "any_step_edge_without_named_target",
                False,
                PathsV2ElementSelector(elementType=PathsV2ElementType.EDGE, anyStep=True, source=_item("a")),
            ),
            (
                "any_step_edge_with_pinned_step",
                False,
                PathsV2ElementSelector(
                    elementType=PathsV2ElementType.EDGE,
                    anyStep=True,
                    stepIndex=0,
                    source=_item("a"),
                    target=_item("b"),
                ),
            ),
            (
                "any_step_edge_in_anchored_mode",
                True,
                PathsV2ElementSelector(
                    elementType=PathsV2ElementType.EDGE, anyStep=True, source=_item("a"), target=_item("b")
                ),
            ),
            (
                "chain_in_open_mode",
                False,
                PathsV2ElementSelector(elementType=PathsV2ElementType.CHAIN, chain=[_item("a")]),
            ),
            ("empty_chain", True, PathsV2ElementSelector(elementType=PathsV2ElementType.CHAIN, chain=[])),
        ]
    )
    def test_invalid_element_selectors_reject(
        self, _name: str, anchored: bool, element: PathsV2ElementSelector
    ) -> None:
        with self.assertRaises(ValidationError):
            self._runner(anchored=anchored).to_actors_query(element)


class TestPathsV2ActorsQueryAPI(ClickhouseTestMixin, APIBaseTest):
    def test_modal_actors_query_round_trips_through_the_query_api(self):
        persons = journeys_for(team=self.team, events_by_person=_timeline("p1", "a", "b"))

        response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "ActorsQuery",
                    "select": ["id"],
                    "source": {
                        "kind": "PathsV2ActorsQuery",
                        "source": {
                            "kind": "PathsV2Query",
                            "dateRange": {"date_from": "2023-03-01", "date_to": "2023-03-31"},
                            "pathsV2Filter": {"stepSources": [{"event": "a"}, {"event": "b"}]},
                        },
                        "element": {"elementType": "node", "stepIndex": 0, "item": {"event": "a"}},
                    },
                }
            },
        )

        self.assertEqual(response.status_code, 200, response.json())
        results = response.json()["results"]
        self.assertEqual([row[0] for row in results], [str(persons["p1"].uuid)])
