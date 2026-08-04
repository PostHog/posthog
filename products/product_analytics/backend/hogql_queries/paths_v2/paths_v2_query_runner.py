from datetime import datetime
from functools import cached_property
from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    CachedPathsV2QueryResponse,
    FunnelConversionWindowTimeUnit,
    PathsV2Edge,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    PathsV2QueryResponse,
    PathsV2Results,
    PathsV2Row,
    PathsV2Step,
    PathsV2StepSource,
    ResolvedDateRangeResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY, HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.funnels.utils import CONVERSION_WINDOW_INTERVAL_BOUNDS, conversion_window_to_seconds
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.validation.validation import QueryValidationContext, QueryValidationRule

from products.product_analytics.backend.hogql_queries.paths_v2.path_item import (
    DEFAULT_COLLAPSE_REPEATS,
    DEFAULT_GAP_INTERVAL,
    DEFAULT_GAP_INTERVAL_UNIT,
    DEFAULT_MAX_ROWS_PER_STEP,
    DEFAULT_MAX_STEPS,
    PATHS_V2_OTHER,
    path_item_expr,
    resolve_step_sources,
    source_events_filter_expr,
)

ELEMENT_KIND_NODE = "node"
ELEMENT_KIND_EDGE = "edge"
ELEMENT_KIND_DROP_OFF = "dropoff"


class ValidateGapBounds:
    """Reject gaps outside the shared funnel conversion window bounds; never clamp."""

    code = "paths_v2_gap_out_of_bounds"

    def validate(self, context: QueryValidationContext[PathsV2Query]) -> None:
        paths_filter = context.query.pathsV2Filter
        if paths_filter is None or paths_filter.gapInterval is None:
            return
        unit = paths_filter.gapIntervalUnit or DEFAULT_GAP_INTERVAL_UNIT
        lower, upper = CONVERSION_WINDOW_INTERVAL_BOUNDS[unit]
        if not lower <= paths_filter.gapInterval <= upper:
            raise ValidationError(
                f"gapInterval must be between {lower} and {upper} for unit {unit.value!r}.",
                code=self.code,
            )


class ValidateStepSources:
    """Step sources must name distinct, non-empty events, as each event maps to one item derivation."""

    code = "paths_v2_step_sources_invalid"

    def validate(self, context: QueryValidationContext[PathsV2Query]) -> None:
        paths_filter = context.query.pathsV2Filter
        if paths_filter is None or paths_filter.stepSources is None:
            return
        events = [source.event for source in paths_filter.stepSources]
        if any(event == "" for event in events):
            raise ValidationError("stepSources must not contain an empty event name.", code=self.code)
        if len(set(events)) != len(events):
            raise ValidationError("stepSources must not contain duplicate events.", code=self.code)


class PathsV2QueryRunner(AnalyticsQueryRunner[PathsV2QueryResponse]):
    query: PathsV2Query
    cached_response: CachedPathsV2QueryResponse

    def validators(self) -> tuple[QueryValidationRule[PathsV2Query], ...]:
        return (ValidateGapBounds(), ValidateStepSources())

    @cached_property
    def paths_v2_filter(self) -> PathsV2Filter:
        return self.query.pathsV2Filter or PathsV2Filter()

    @cached_property
    def step_sources(self) -> list[PathsV2StepSource]:
        return resolve_step_sources(self.query)

    @property
    def max_steps(self) -> int:
        if self.paths_v2_filter.maxSteps is not None:
            return self.paths_v2_filter.maxSteps
        return DEFAULT_MAX_STEPS

    @property
    def max_rows_per_step(self) -> int:
        if self.paths_v2_filter.maxRowsPerStep is not None:
            return self.paths_v2_filter.maxRowsPerStep
        return DEFAULT_MAX_ROWS_PER_STEP

    @property
    def gap_interval(self) -> int:
        if self.paths_v2_filter.gapInterval is not None:
            return self.paths_v2_filter.gapInterval
        return DEFAULT_GAP_INTERVAL

    @property
    def gap_interval_unit(self) -> FunnelConversionWindowTimeUnit:
        if self.paths_v2_filter.gapIntervalUnit is not None:
            return self.paths_v2_filter.gapIntervalUnit
        return DEFAULT_GAP_INTERVAL_UNIT

    @property
    def collapse_repeats(self) -> bool:
        if self.paths_v2_filter.collapseRepeats is not None:
            return self.paths_v2_filter.collapseRepeats
        return DEFAULT_COLLAPSE_REPEATS

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=datetime.now())

    @property
    def result_row_limit(self) -> int:
        """Exact upper bound of result rows for the configured grid, so the generic default
        LIMIT 100 can never silently truncate results: per step one row per top item plus the
        other row and a drop-off row, and per adjacent step pair one edge row per (source, target)
        combination of top items and the other bucket."""
        rows_per_step = self.max_rows_per_step + 1
        node_rows = self.max_steps * rows_per_step
        drop_off_rows = self.max_steps
        edge_rows = (self.max_steps - 1) * rows_per_step * rows_per_step
        return node_rows + drop_off_rows + edge_rows

    def _gap_expr(self) -> ast.Expr:
        # Fixed seconds via the funnels realization (month means 31 days), never calendar INTERVAL
        # arithmetic, so a journey's gap G always equals the emitted funnel's conversion window.
        return parse_expr(
            f"toIntervalSecond({conversion_window_to_seconds(self.gap_interval, self.gap_interval_unit)})"
        )

    def _event_base_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """One row per in-range event matching a step source: (timestamp, actor_id, path_item)."""
        event_filters: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=self.query_date_range.date_from_to_start_of_interval_hogql(),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=self.query_date_range.date_to_as_hogql(),
            ),
            source_events_filter_expr(self.step_sources),
        ]

        if self.query.properties is not None and self.query.properties != []:
            event_filters.append(property_to_expr(self.query.properties, self.team))

        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for prop in self.team.test_account_filters:
                event_filters.append(property_to_expr(prop, self.team))

        return parse_select(
            """
            SELECT
                timestamp,
                person_id AS actor_id,
                {path_item} AS path_item
            FROM events
            WHERE {filters}
            """,
            placeholders={
                "path_item": path_item_expr(self.step_sources, self.team),
                "filters": ast.And(exprs=event_filters),
            },
        )

    def _elements_per_actor_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Per actor: build journeys, then flatten them into the elements the actor touches.

        - Events sort by time and split into journeys wherever the inactivity gap exceeds gap G
          (a gap of exactly G keeps the journey together, matching the funnel conversion window's
          inclusive comparison).
        - Immediate repeats of the same path item collapse when collapseRepeats is on.
        - Journeys keep only their first maxSteps items.
        - Elements are tuples of (kind, step index, item, target item):
          a node per journey position, an edge per adjacent position pair, and a drop-off at the
          journey's final length when the journey ends within the grid.
        """
        if self.collapse_repeats:
            collapsed_journeys_expr = parse_expr(
                "arrayMap(journey -> arrayFilter((item, i) -> i = 1 OR item != journey[i - 1], journey, arrayEnumerate(journey)), journey_items)"
            )
        else:
            collapsed_journeys_expr = ast.Field(chain=["journey_items"])

        return parse_select(
            """
            SELECT
                actor_id,
                arraySort(x -> x.1, groupArray(tuple(timestamp, path_item))) AS event_tuples,
                arrayPopBack(arrayPushFront(arrayMap(x -> x.1, event_tuples), NULL)) AS previous_timestamps,
                arraySplit((x, previous_timestamp) -> ifNull(x.1 > previous_timestamp + {gap}, 1), event_tuples, previous_timestamps) AS journeys,
                arrayMap(journey -> arrayMap(event_tuple -> event_tuple.2, journey), journeys) AS journey_items,
                {collapsed_journeys} AS collapsed_journeys,
                arrayMap(journey -> arraySlice(journey, 1, {max_steps}), collapsed_journeys) AS trimmed_journeys,
                arrayFlatten(arrayMap(journey -> arrayMap((item, i) -> tuple({node_kind}, i, item, {no_item}), journey, arrayEnumerate(journey)), trimmed_journeys)) AS node_elements,
                arrayFlatten(arrayMap(journey -> arrayMap((pair, i) -> tuple({edge_kind}, i, pair.1, pair.2), arrayZip(arrayPopBack(journey), arrayPopFront(journey)), arrayEnumerate(arrayZip(arrayPopBack(journey), arrayPopFront(journey)))), trimmed_journeys)) AS edge_elements,
                arrayMap(journey_length -> tuple({drop_off_kind}, journey_length, {no_item}, {no_item}), arrayFilter(journey_length -> journey_length <= {max_steps}, arrayMap(journey -> length(journey), collapsed_journeys))) AS drop_off_elements,
                arrayConcat(node_elements, edge_elements, drop_off_elements) AS elements
            FROM {event_base_query}
            GROUP BY actor_id
            """,
            placeholders={
                "event_base_query": self._event_base_query(),
                "gap": self._gap_expr(),
                "collapsed_journeys": collapsed_journeys_expr,
                "max_steps": ast.Constant(value=self.max_steps),
                "node_kind": ast.Constant(value=ELEMENT_KIND_NODE),
                "edge_kind": ast.Constant(value=ELEMENT_KIND_EDGE),
                "drop_off_kind": ast.Constant(value=ELEMENT_KIND_DROP_OFF),
                "no_item": parse_expr("tuple('', '')"),
            },
        )

    def _element_counts_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Unique actors per element. The state is kept alongside the finalized count so the
        top-N bucketing stage can merge non-top items into the other bucket without double
        counting actors that touch several of them."""
        return parse_select(
            """
            SELECT
                element.1 AS kind,
                element.2 AS step_index,
                element.3 AS item,
                element.4 AS target_item,
                uniqExact(actor_id) AS actor_count,
                uniqExactState(actor_id) AS actor_state
            FROM {elements_per_actor_query}
            ARRAY JOIN elements AS element
            GROUP BY kind, step_index, item, target_item
            """,
            placeholders={"elements_per_actor_query": self._elements_per_actor_query()},
        )

    def _ranked_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Rank node rows per step by unique-actor count; the top maxRowsPerStep stay named."""
        return parse_select(
            """
            SELECT
                kind,
                step_index,
                item,
                target_item,
                actor_count,
                actor_state,
                row_number() OVER (PARTITION BY kind, step_index ORDER BY actor_count DESC, item.1 ASC, item.2 ASC) AS row_rank
            FROM {element_counts_query}
            """,
            placeholders={"element_counts_query": self._element_counts_query()},
        )

    def _bucketed_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Attach each element's endpoint top-ness. Edges look their source up among the nodes of
        their own step and their target among the nodes of the following step, since node ranks
        exist only on node rows."""
        return parse_select(
            """
            SELECT
                kind,
                step_index,
                item,
                target_item,
                actor_state,
                max(if(kind = {node_kind} AND row_rank <= {max_rows_per_step}, 1, 0)) OVER (PARTITION BY step_index, item) AS source_is_top,
                max(if(kind = {node_kind} AND row_rank <= {max_rows_per_step}, 1, 0)) OVER (PARTITION BY if(kind = {edge_kind}, step_index + 1, step_index), if(kind = {edge_kind}, target_item, item)) AS target_is_top
            FROM {ranked_query}
            """,
            placeholders={
                "ranked_query": self._ranked_query(),
                "max_rows_per_step": ast.Constant(value=self.max_rows_per_step),
                "node_kind": ast.Constant(value=ELEMENT_KIND_NODE),
                "edge_kind": ast.Constant(value=ELEMENT_KIND_EDGE),
            },
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Final per-element unique-actor counts, with non-top items merged into the other bucket.

        Merging happens on the aggregate states, so an actor that touches several bucketed items
        still counts once. Drop-off rows keep their placeholder item, since they are per step."""
        query = parse_select(
            """
            SELECT
                kind,
                step_index,
                multiIf(kind = {drop_off_kind}, item, source_is_top = 1, item, {other_item}) AS source_item,
                multiIf(kind != {edge_kind}, target_item, target_is_top = 1, target_item, {other_item}) AS grouped_target_item,
                uniqExactMerge(actor_state) AS actor_count
            FROM {bucketed_query}
            GROUP BY kind, step_index, source_item, grouped_target_item
            ORDER BY kind ASC, step_index ASC, actor_count DESC, source_item ASC, grouped_target_item ASC
            """,
            placeholders={
                "bucketed_query": self._bucketed_query(),
                "drop_off_kind": ast.Constant(value=ELEMENT_KIND_DROP_OFF),
                "edge_kind": ast.Constant(value=ELEMENT_KIND_EDGE),
                "other_item": parse_expr("tuple({other}, '')", {"other": ast.Constant(value=PATHS_V2_OTHER)}),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        query.limit = ast.Constant(value=self.result_row_limit)
        return query

    def _to_path_item(self, item: tuple[str, str]) -> PathsV2Item | None:
        event, label = item
        if event == PATHS_V2_OTHER:
            return None
        for source in self.step_sources:
            if source.event == event:
                return PathsV2Item(event=event, label=label if source.namingProperty is not None else None)
        return PathsV2Item(event=event, label=label)

    def _to_results(self, rows: list[tuple[Any, ...]]) -> PathsV2Results:
        steps: dict[int, PathsV2Step] = {}
        edges: list[PathsV2Edge] = []

        def step_for(one_based_index: int) -> PathsV2Step:
            step_index = one_based_index - 1
            if step_index not in steps:
                steps[step_index] = PathsV2Step(stepIndex=step_index, rows=[], otherCount=0, dropOffCount=0)
            return steps[step_index]

        for kind, step_index, source_item, target_item, actor_count in rows:
            if kind == ELEMENT_KIND_DROP_OFF:
                step_for(step_index).dropOffCount = actor_count
            elif kind == ELEMENT_KIND_NODE:
                item = self._to_path_item(source_item)
                if item is None:
                    step_for(step_index).otherCount = actor_count
                else:
                    step_for(step_index).rows.append(PathsV2Row(item=item, count=actor_count))
            elif kind == ELEMENT_KIND_EDGE:
                edges.append(
                    PathsV2Edge(
                        stepIndex=step_index - 1,
                        source=self._to_path_item(source_item),
                        target=self._to_path_item(target_item),
                        count=actor_count,
                    )
                )

        def item_sort_key(item: PathsV2Item | None) -> tuple[bool, str, str]:
            # The other bucket (None) sorts after named items.
            if item is None:
                return (True, "", "")
            return (False, item.event, item.label or "")

        for step in steps.values():
            step.rows.sort(key=lambda row: (-row.count, row.item.event, row.item.label or ""))
        edges.sort(
            key=lambda edge: (edge.stepIndex, -edge.count, item_sort_key(edge.source), item_sort_key(edge.target))
        )

        return PathsV2Results(steps=[steps[index] for index in sorted(steps)], edges=edges)

    def _calculate(self) -> PathsV2QueryResponse:
        query = self.to_query()
        # Display-only response HogQL (never executed); bypass warehouse ACL so printing doesn't fail closed userless.
        hogql = to_printed_hogql(query, self.team, bypass_warehouse_access_control=True)

        response = execute_hogql_query(
            query_type="PathsV2Query",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(
                # Same spill-to-disk guard funnels use, since per-actor event arrays are unbounded
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
            ),
        )

        assert response.results is not None
        return PathsV2QueryResponse(
            results=self._to_results(response.results),
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
