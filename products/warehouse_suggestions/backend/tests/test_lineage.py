from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_suggestions.backend.logic.lineage import recomputing_consumers

VIEW, MIDDLE, CONSUMER, BEYOND = uuid4(), uuid4(), uuid4(), uuid4()


class TestRecomputingConsumers(SimpleTestCase):
    @parameterized.expand(
        [
            ("through_a_view_that_is_not_materialized", {VIEW: [MIDDLE], MIDDLE: [CONSUMER]}, {CONSUMER}, {CONSUMER}),
            (
                "stops_at_the_first_materialized_view",
                {VIEW: [CONSUMER], CONSUMER: [BEYOND]},
                {CONSUMER, BEYOND},
                {CONSUMER},
            ),
            ("survives_a_cycle", {VIEW: [MIDDLE], MIDDLE: [VIEW, CONSUMER]}, {CONSUMER}, {CONSUMER}),
        ]
    )
    def test_finds_the_materialized_views_whose_refreshes_compute_it(
        self, _name: str, dependents: dict, materialized: set, expected: set
    ) -> None:
        assert recomputing_consumers(VIEW, dependents, materialized) == expected
