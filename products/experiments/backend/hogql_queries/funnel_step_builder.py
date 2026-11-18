from typing import Union

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast

from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.base_query_utils import event_or_action_to_filter


class FunnelStepBuilder:
    """
    Builds step column expressions for funnel queries in one of two patterns:

    1. **Boolean columns**: For events-only funnels where all steps are evaluated
       in a single query against the events table. Each step is a boolean expression.

    2. **Constant columns**: For UNION ALL queries with heterogeneous sources
       (events + datawarehouse). Each subquery represents one step, with the
       active step set to 1 and all others set to 0.
    """

    def __init__(
        self,
        series: list[Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]],
        team: Team,
    ):
        self.series = series
        self.team = team
        # +1 for step_0, the exposure step
        self.num_steps = len(series) + 1

    def build_boolean_columns(self, exposure_filter: ast.Expr) -> list[ast.Alias]:
        """
        Step columns for a funnel where all steps come from the events table, so
        no UNION is necessary. Each event row gets the 0/1 columns
        [step_0, step_1, ..., step_N], with `exposure_filter` as step_0.
        """
        columns = []

        columns.append(
            ast.Alias(
                alias="step_0",
                expr=exposure_filter,
            )
        )

        for step_index, step_source in enumerate(self.series, start=1):
            step_filter = self._build_step_filter(step_source)
            columns.append(
                ast.Alias(
                    alias=f"step_{step_index}",
                    expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
                )
            )

        return columns

    def build_constant_columns(self, active_step_index: int) -> list[ast.Alias]:
        """
        Step columns as constants for one subquery of a UNION ALL, where each
        subquery represents one step. The active step is 1 and all other steps are 0.

        A funnel that combines events and data warehouse sources needs this pattern,
        because each source needs its own subquery with different table references
        and fields.
        """
        if active_step_index < 0 or active_step_index >= self.num_steps:
            raise ValueError(
                f"active_step_index {active_step_index} is out of bounds. "
                f"Must be between 0 and {self.num_steps - 1} (inclusive)."
            )

        columns = []

        for step_index in range(self.num_steps):
            value = 1 if step_index == active_step_index else 0
            columns.append(
                ast.Alias(
                    alias=f"step_{step_index}",
                    expr=ast.Constant(value=value),
                )
            )

        return columns

    def _build_step_filter(self, step_source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]) -> ast.Expr:
        if isinstance(step_source, ExperimentDataWarehouseNode):
            raise ValueError(
                f"Cannot build boolean filter for {type(step_source).__name__}. "
                "Use constant columns for UNION ALL queries with datawarehouse sources."
            )

        return event_or_action_to_filter(self.team, step_source)
