from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from products.experiments.backend.hogql_queries.base_query_utils import (
    quantile_exact_position,
    winsorization_bound_expr,
)


class TestWinsorizationBound(ClickhouseTestMixin, BaseTest):
    @parameterized.expand([(0.99, 100), (0.99, 101), (0.95, 766), (0.999, 600), (0.5, 7)])
    def test_quantile_exact_position_tells_when_the_upper_bound_is_zero(self, level: float, count: int) -> None:
        hidden = count - quantile_exact_position(level, count) - 1

        bounds = []
        for with_value in (hidden, hidden + 1):
            query = parse_select(
                f"SELECT {{bound}} FROM (SELECT if(number >= {count - with_value}, 5, 0) AS value FROM numbers({count}))",
                placeholders={"bound": winsorization_bound_expr(level, "value")},
            )
            bounds.append(execute_hogql_query(query, team=self.team).results[0][0])

        self.assertEqual(bounds, [0, 5])
