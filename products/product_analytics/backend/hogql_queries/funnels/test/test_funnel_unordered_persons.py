from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, EventsNode, FunnelsFilter, FunnelsQuery, IntervalType, StepOrderValue

from posthog.test.test_journeys import journeys_for

from products.product_analytics.backend.hogql_queries.funnels.test.test_funnel_persons import get_actors

FORMAT_TIME = "%Y-%m-%d 00:00:00"


def unordered_funnel_query() -> FunnelsQuery:
    return FunnelsQuery(
        series=[
            EventsNode(event="step one", name="step one"),
            EventsNode(event="step two", name="step two"),
            EventsNode(event="step three", name="step three"),
        ],
        interval=IntervalType.DAY,
        dateRange=DateRange(date_from="2021-05-01 00:00:00", date_to="2021-05-07 00:00:00"),
        funnelsFilter=FunnelsFilter(funnelOrderType=StepOrderValue.UNORDERED),
    )


class TestFunnelUnorderedStepsPersons(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data_multiple_dropoffs(self):
        events_by_person = {}
        for i in range(5):
            events_by_person[f"user_{i}"] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                {"event": "step three", "timestamp": datetime(2021, 5, 3)},
                {"event": "step two", "timestamp": datetime(2021, 5, 5)},
            ]

        for i in range(5, 15):
            events_by_person[f"user_{i}"] = [
                {"event": "step two", "timestamp": datetime(2021, 5, 1)},
                {"event": "step one", "timestamp": datetime(2021, 5, 3)},
            ]

        for i in range(15, 35):
            events_by_person[f"user_{i}"] = [{"event": "step one", "timestamp": datetime(2021, 5, 1)}]

        journeys_for(events_by_person, self.team)

    def test_invalid_steps(self):
        query = unordered_funnel_query()

        with self.assertRaisesMessage(ValueError, "Input should be a valid integer"):
            get_actors(query, self.team, funnel_step="blah")  # type: ignore

        with self.assertRaisesMessage(ValueError, "Funnel steps are 1-indexed, so step 0 doesn't exist"):
            get_actors(query, self.team, funnel_step=0)

        with self.assertRaisesMessage(ValueError, "The first valid drop-off argument for funnelStep is -2"):
            get_actors(query, self.team, funnel_step=-1)

    def test_first_step(self):
        self._create_sample_data_multiple_dropoffs()

        results = get_actors(unordered_funnel_query(), self.team, funnel_step=1)

        self.assertEqual(35, len(results))

    def test_last_step(self):
        self._create_sample_data_multiple_dropoffs()

        results = get_actors(unordered_funnel_query(), self.team, funnel_step=3)

        self.assertEqual(5, len(results))

    def test_second_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()

        results = get_actors(unordered_funnel_query(), self.team, funnel_step=-2)

        self.assertEqual(20, len(results))

    def test_last_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()

        results = get_actors(unordered_funnel_query(), self.team, funnel_step=-3)

        self.assertEqual(10, len(results))
