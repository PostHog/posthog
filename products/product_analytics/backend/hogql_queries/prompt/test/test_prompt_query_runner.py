from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from posthog.schema import DateRange, EventsNode, InsightVizNode, PromptQuery, PromptQueryResponse, TrendsQuery

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner

from products.product_analytics.backend.hogql_queries.prompt.prompt_query_runner import PromptQueryRunner


@freeze_time("2024-01-10T12:00:00Z")
class TestPromptQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_pageviews(self) -> None:
        _create_person(distinct_ids=["p1"], team=self.team)
        for day in ("2024-01-08", "2024-01-09"):
            _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp=f"{day}T10:00:00Z")
        flush_persons_and_events()

    def _trends_snapshot(self) -> InsightVizNode:
        return InsightVizNode(
            source=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                dateRange=DateRange(date_from="2024-01-07", date_to="2024-01-10"),
            )
        )

    def test_empty_prompt_query_uses_prompt_runner_and_returns_no_results(self) -> None:
        runner = get_query_runner(PromptQuery(prompt="how many pageviews?"), self.team)
        assert isinstance(runner, PromptQueryRunner)

        response = runner.calculate()
        assert isinstance(response, PromptQueryResponse)
        assert response.results == []

    def test_prompt_query_with_snapshot_delegates_to_inner_runner(self) -> None:
        runner = get_query_runner(
            PromptQuery(prompt="pageviews over time", generatedQuery=self._trends_snapshot()),
            self.team,
        )
        # A generated snapshot is unwrapped to its native runner so it caches and renders like the
        # insight it generated — never the PromptQueryRunner.
        assert isinstance(runner, TrendsQueryRunner)

    def test_prompt_snapshot_matches_running_the_inner_query_directly(self) -> None:
        self._create_pageviews()
        snapshot = self._trends_snapshot()

        via_prompt = get_query_runner(PromptQuery(prompt="x", generatedQuery=snapshot), self.team).calculate()
        direct = get_query_runner(snapshot.source, self.team).calculate()

        assert via_prompt.results == direct.results
