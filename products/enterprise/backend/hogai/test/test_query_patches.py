from posthog.test.base import BaseTest

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    ActorsPropertyTaxonomyResponse,
    EventTaxonomyItem,
    EventTaxonomyQuery,
    TeamTaxonomyItem,
    TeamTaxonomyQuery,
)

from products.enterprise.backend.hogai.eval.offline.query_patches import (
    ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE,
    EVENT_TAXONOMY_QUERY_DATA_SOURCE,
    TEAM_TAXONOMY_QUERY_DATA_SOURCE,
    PatchedActorsPropertyTaxonomyQueryRunner,
    PatchedEventTaxonomyQueryRunner,
    PatchedTeamTaxonomyQueryRunner,
)


class TestQueryPatches(BaseTest):
    def setUp(self):
        super().setUp()
        TEAM_TAXONOMY_QUERY_DATA_SOURCE[self.team.id] = [
            TeamTaxonomyItem(count=10, event="$pageview"),
        ]
        EVENT_TAXONOMY_QUERY_DATA_SOURCE[self.team.id] = {
            "$pageview": [
                EventTaxonomyItem(property="$browser", sample_values=["Safari"], sample_count=1),
            ],
        }
        ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[self.team.id]["person"] = {
            "$location": ActorsPropertyTaxonomyResponse(sample_values=["US"], sample_count=1),
            "$browser": ActorsPropertyTaxonomyResponse(sample_values=["Safari"], sample_count=10),
        }
        ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[self.team.id][0] = {
            "$device": ActorsPropertyTaxonomyResponse(sample_values=["Phone"], sample_count=1),
        }

    def tearDown(self):
        super().tearDown()
        TEAM_TAXONOMY_QUERY_DATA_SOURCE.clear()
        EVENT_TAXONOMY_QUERY_DATA_SOURCE.clear()
        ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE.clear()

    def test_patched_team_taxonomy_query_runner_returns_result(self):
        query_runner = PatchedTeamTaxonomyQueryRunner(
            team=self.team,
            query=TeamTaxonomyQuery(),
        ).calculate()
        self.assertEqual(query_runner.results, [TeamTaxonomyItem(count=10, event="$pageview")])

    def test_patched_team_taxonomy_query_runner_handles_no_results(self):
        TEAM_TAXONOMY_QUERY_DATA_SOURCE.clear()
        query_runner = PatchedTeamTaxonomyQueryRunner(
            team=self.team,
            query=TeamTaxonomyQuery(),
        ).calculate()
        self.assertEqual(query_runner.results, [])

    def test_patched_event_taxonomy_query_runner_returns_result(self):
        query_runner = PatchedEventTaxonomyQueryRunner(
            team=self.team,
            query=EventTaxonomyQuery(event="$pageview"),
        ).calculate()
        self.assertEqual(
            query_runner.results, [EventTaxonomyItem(property="$browser", sample_values=["Safari"], sample_count=1)]
        )

    def test_patched_event_taxonomy_query_runner_handles_no_results(self):
        EVENT_TAXONOMY_QUERY_DATA_SOURCE.clear()
        query_runner = PatchedEventTaxonomyQueryRunner(
            team=self.team,
            query=EventTaxonomyQuery(event="$pageview"),
        ).calculate()
        self.assertEqual(query_runner.results, [])

    def test_patched_event_taxonomy_query_runner_returns_result_for_action_id(self):
        EVENT_TAXONOMY_QUERY_DATA_SOURCE[self.team.id][123] = [
            EventTaxonomyItem(property="$browser", sample_values=["Safari"], sample_count=1),
        ]
        query_runner = PatchedEventTaxonomyQueryRunner(
            team=self.team,
            query=EventTaxonomyQuery(actionId=123),
        ).calculate()
        self.assertEqual(
            query_runner.results,
            [EventTaxonomyItem(property="$browser", sample_values=["Safari"], sample_count=1)],
        )

    def test_patched_actors_property_taxonomy_query_runner_returns_result(self):
        query_runner = PatchedActorsPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorsPropertyTaxonomyQuery(groupTypeIndex=0, properties=["$device"]),
        ).calculate()
        self.assertEqual(
            query_runner.results,
            [ActorsPropertyTaxonomyResponse(sample_values=["Phone"], sample_count=1)],
        )

        query_runner = PatchedActorsPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorsPropertyTaxonomyQuery(properties=["$location", "$browser"]),
        ).calculate()
        self.assertEqual(
            query_runner.results,
            [
                ActorsPropertyTaxonomyResponse(sample_values=["US"], sample_count=1),
                ActorsPropertyTaxonomyResponse(sample_values=["Safari"], sample_count=10),
            ],
        )

    def test_patched_actors_property_taxonomy_query_runner_handles_mixed_results(self):
        query_runner = PatchedActorsPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorsPropertyTaxonomyQuery(properties=["$location", "$latitude"]),
        ).calculate()
        self.assertEqual(
            query_runner.results,
            [
                ActorsPropertyTaxonomyResponse(sample_values=["US"], sample_count=1),
                ActorsPropertyTaxonomyResponse(sample_values=[], sample_count=0),
            ],
        )

    def test_patched_actors_property_taxonomy_query_runner_handles_no_results(self):
        ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE.clear()
        query_runner = PatchedActorsPropertyTaxonomyQueryRunner(
            team=self.team,
            query=ActorsPropertyTaxonomyQuery(properties=["$device"]),
        ).calculate()
        self.assertEqual(query_runner.results, [ActorsPropertyTaxonomyResponse(sample_values=[], sample_count=0)])
