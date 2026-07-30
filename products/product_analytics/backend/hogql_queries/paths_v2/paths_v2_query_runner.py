from datetime import datetime
from functools import cached_property
from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    CachedPathsV2QueryResponse,
    FunnelConversionWindowTimeUnit,
    PathsV2Anchor,
    PathsV2AnchorType,
    PathsV2Edge,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Prefix,
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
    DEFAULT_CONVERSION_WINDOW_INTERVAL,
    DEFAULT_CONVERSION_WINDOW_INTERVAL_UNIT,
    DEFAULT_GAP_INTERVAL,
    DEFAULT_GAP_INTERVAL_UNIT,
    DEFAULT_MAX_ROWS_PER_STEP,
    DEFAULT_MAX_STEPS,
    PATHS_V2_OTHER,
    excluded_item_tuples,
    excluded_items_filter_expr,
    item_tuple_expr,
    path_item_expr,
    resolve_cleaning_rules,
    resolve_step_sources,
    source_events_filter_expr,
    step_source_for_event,
)

ELEMENT_KIND_NODE = "node"
ELEMENT_KIND_EDGE = "edge"
ELEMENT_KIND_DROP_OFF = "dropoff"

# Anchored mode carries per-chain prefix counts for the hover funnel preview. This caps how many the
# runner returns, keeping the response bounded on large teams; the most common chains (which include
# every visible top-item chain) survive the descending-count ordering, and the long tail of chains
# through non-top items is dropped from the hover data only — the grid and persons modal stay whole.
MAX_PREFIX_ROWS = 10_000


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


class ValidateWindowBounds:
    """Reject anchored windows outside the shared funnel conversion window bounds; never clamp. The
    window is reused verbatim as the emitted funnel's conversion window, so it must stay in bounds."""

    code = "paths_v2_window_out_of_bounds"

    def validate(self, context: QueryValidationContext[PathsV2Query]) -> None:
        paths_filter = context.query.pathsV2Filter
        if paths_filter is None or paths_filter.conversionWindowInterval is None:
            return
        unit = paths_filter.conversionWindowIntervalUnit or DEFAULT_CONVERSION_WINDOW_INTERVAL_UNIT
        lower, upper = CONVERSION_WINDOW_INTERVAL_BOUNDS[unit]
        if not lower <= paths_filter.conversionWindowInterval <= upper:
            raise ValidationError(
                f"conversionWindowInterval must be between {lower} and {upper} for unit {unit.value!r}.",
                code=self.code,
            )


class ValidateAnchor:
    """An anchor's event must be one of the step sources, otherwise no event could ever derive it and
    the chart would be empty for a reason the config does not reveal. When that source names its items
    by a property, the anchor must carry the label that pins which item it is."""

    code = "paths_v2_anchor_invalid"

    def validate(self, context: QueryValidationContext[PathsV2Query]) -> None:
        paths_filter = context.query.pathsV2Filter
        if paths_filter is None or paths_filter.anchor is None:
            return
        anchor_item = paths_filter.anchor.item
        source = next((s for s in resolve_step_sources(context.query) if s.event == anchor_item.event), None)
        if source is None:
            raise ValidationError(
                f"The anchor event {anchor_item.event!r} must be one of the step sources.",
                code=self.code,
            )
        if source.namingProperty is not None and anchor_item.label is None:
            raise ValidationError(
                f"The anchor item for event {anchor_item.event!r} needs a label, as its source has a naming property.",
                code=self.code,
            )


class ValidateExcludedItems:
    """Excluding an item of a naming-property source needs a label, since a bare event does not pin
    which item to drop. Excluding the anchor would empty the chart for a reason the config does not
    reveal. Exclusions whose event is not a step source are allowed and inert, so switching sources
    never invalidates a saved exclude list."""

    code = "paths_v2_excluded_items_invalid"

    def validate(self, context: QueryValidationContext[PathsV2Query]) -> None:
        paths_filter = context.query.pathsV2Filter
        if paths_filter is None or not paths_filter.excludedItems:
            return
        sources_by_event = {source.event: source for source in resolve_step_sources(context.query)}
        for item in paths_filter.excludedItems:
            source = sources_by_event.get(item.event)
            if source is not None and source.namingProperty is not None and item.label is None:
                raise ValidationError(
                    f"The excluded item for event {item.event!r} needs a label, as its source has a naming property.",
                    code=self.code,
                )
        if paths_filter.anchor is not None:
            anchor_item = paths_filter.anchor.item
            if (anchor_item.event, anchor_item.label or "") in excluded_item_tuples(paths_filter):
                raise ValidationError(
                    "The anchor cannot be an excluded item, as no journey could ever reach it.",
                    code=self.code,
                )


class PathsV2QueryRunner(AnalyticsQueryRunner[PathsV2QueryResponse]):
    query: PathsV2Query
    cached_response: CachedPathsV2QueryResponse

    def validators(self) -> tuple[QueryValidationRule[PathsV2Query], ...]:
        return (
            ValidateGapBounds(),
            ValidateWindowBounds(),
            ValidateStepSources(),
            ValidateAnchor(),
            ValidateExcludedItems(),
        )

    @cached_property
    def paths_v2_filter(self) -> PathsV2Filter:
        return self.query.pathsV2Filter or PathsV2Filter()

    @cached_property
    def step_sources(self) -> list[PathsV2StepSource]:
        return resolve_step_sources(self.query)

    @cached_property
    def cleaning_rules(self) -> list[tuple[str, str]]:
        return resolve_cleaning_rules(self.query.pathsV2Filter, self.team)

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

    @property
    def anchor(self) -> PathsV2Anchor | None:
        return self.paths_v2_filter.anchor

    @property
    def is_anchored(self) -> bool:
        """Anchored mode when an anchor is set: one sequence per actor within window W, every segment a
        plain funnel. Otherwise open mode: gap-split journeys."""
        return self.anchor is not None

    @property
    def window_interval(self) -> int:
        if self.paths_v2_filter.conversionWindowInterval is not None:
            return self.paths_v2_filter.conversionWindowInterval
        return DEFAULT_CONVERSION_WINDOW_INTERVAL

    @property
    def window_interval_unit(self) -> FunnelConversionWindowTimeUnit:
        if self.paths_v2_filter.conversionWindowIntervalUnit is not None:
            return self.paths_v2_filter.conversionWindowIntervalUnit
        return DEFAULT_CONVERSION_WINDOW_INTERVAL_UNIT

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

    def _window_interval_expr(self) -> ast.Expr:
        # Window W realized the same fixed-seconds way as the gap, so it always equals the emitted
        # funnel's conversion window.
        return parse_expr(
            f"toIntervalSecond({conversion_window_to_seconds(self.window_interval, self.window_interval_unit)})"
        )

    def _split_interval_expr(self) -> ast.Expr:
        """The interval that splits an actor's events into journeys. Open mode splits on gap G. Anchored
        mode splits on window W: the anchor prefilter already bounds every kept event to within W of the
        anchor, so no adjacent pair can exceed W and the actor's events stay a single sequence."""
        if self.is_anchored:
            return self._window_interval_expr()
        return self._gap_expr()

    def _sorted_events_expr(self) -> ast.Expr:
        """The per-actor event tuples in the order the grid reads them. Ascending time everywhere except
        an end anchor, which sorts descending so the anchor (each actor's latest anchor event) lands at
        step 0 and the grid reads backward in time toward it."""
        events = "groupArray(tuple(timestamp, path_item))"
        if self.is_anchored and self.anchor is not None and self.anchor.type == PathsV2AnchorType.END:
            # arrayReverse(arraySort(...)), not arrayReverseSort: HogQL aliases arrayReverseSort to the
            # ascending arraySort, which would silently keep forward order.
            return parse_expr(f"arrayReverse(arraySort(x -> x.1, {events}))")
        return parse_expr(f"arraySort(x -> x.1, {events})")

    def _event_base_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """One row per in-range event matching a step source and no excluded item:
        (timestamp, actor_id, path_item)."""
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

        excluded_filter = excluded_items_filter_expr(
            ast.Field(chain=["path_item"]), excluded_item_tuples(self.query.pathsV2Filter)
        )
        if excluded_filter is not None:
            event_filters.append(excluded_filter)

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
                "path_item": path_item_expr(self.step_sources, self.cleaning_rules),
                "filters": ast.And(exprs=event_filters),
            },
        )

    def _anchor_source(self) -> PathsV2StepSource:
        assert self.anchor is not None
        return step_source_for_event(self.step_sources, self.anchor.item.event)

    def _anchor_item_expr(self) -> ast.Expr:
        assert self.anchor is not None
        return item_tuple_expr(self.anchor.item, self._anchor_source())

    def _anchored_event_base_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Anchored mode's prefilter (a performance guardrail, not an optimization): resolve the anchor
        actors and each actor's anchor timestamp first, then keep only those actors' events within
        window W of their anchor. A start anchor takes the actor's first anchor-item occurrence and the
        events from it forward; an end anchor takes the last occurrence and the events up to it. Either
        way each kept actor contributes exactly the events of their single anchored sequence."""
        assert self.anchor is not None
        if self.anchor.type == PathsV2AnchorType.END:
            anchor_ts_expr = parse_expr("max(timestamp)")
            window_bounds = parse_expr(
                "base.timestamp <= anchor.anchor_ts AND base.timestamp >= anchor.anchor_ts - {window}",
                {"window": self._window_interval_expr()},
            )
        else:
            anchor_ts_expr = parse_expr("min(timestamp)")
            window_bounds = parse_expr(
                "base.timestamp >= anchor.anchor_ts AND base.timestamp <= anchor.anchor_ts + {window}",
                {"window": self._window_interval_expr()},
            )
        return parse_select(
            """
            WITH ranged_events AS ({event_base_query})
            SELECT base.timestamp AS timestamp, base.actor_id AS actor_id, base.path_item AS path_item
            FROM ranged_events AS base
            INNER JOIN (
                SELECT actor_id, {anchor_ts} AS anchor_ts
                FROM ranged_events
                WHERE path_item = {anchor_item}
                GROUP BY actor_id
            ) AS anchor ON base.actor_id = anchor.actor_id
            WHERE {window_bounds}
            """,
            placeholders={
                "event_base_query": self._event_base_query(),
                "anchor_ts": anchor_ts_expr,
                "anchor_item": self._anchor_item_expr(),
                "window_bounds": window_bounds,
            },
        )

    def _events_for_journeys_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """The event rows the journey builder groups: prefiltered to the anchored window in anchored
        mode, the full in-range set in open mode."""
        if self.is_anchored:
            return self._anchored_event_base_query()
        return self._event_base_query()

    def _elements_per_actor_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Per actor: build journeys, then flatten them into the elements the actor touches.

        - Events sort by time and split into journeys wherever the gap exceeds the split interval
          (a gap of exactly the interval keeps the journey together, matching the funnel conversion
          window's inclusive comparison). Open mode splits on gap G; anchored mode splits on window W
          over events the prefilter already bounded to within W of the anchor, so the actor keeps a
          single sequence.
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
                {sorted_events} AS event_tuples,
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
                "event_base_query": self._events_for_journeys_query(),
                "sorted_events": self._sorted_events_expr(),
                "gap": self._split_interval_expr(),
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

    def _anchored_prefix_counts_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Per-chain prefix counts for the hover funnel preview (anchored mode only). Each actor has
        one sequence, so its prefixes nest into the chain tree the hover walks; a prefix's count is the
        unique actors whose sequence begins with exactly that chain. Ordered by descending count and
        capped at MAX_PREFIX_ROWS, so the visible top-item chains are always carried and only long-tail
        chains through non-top items can be dropped from the hover data."""
        return parse_select(
            """
            WITH sequences AS (
                SELECT actor_id, arrayElement(trimmed_journeys, 1) AS sequence
                FROM {elements_per_actor_query}
            )
            SELECT arraySlice(sequence, 1, prefix_length) AS prefix, uniqExact(actor_id) AS actor_count
            FROM sequences
            ARRAY JOIN arrayEnumerate(sequence) AS prefix_length
            GROUP BY prefix
            ORDER BY actor_count DESC, length(prefix) ASC, prefix ASC
            LIMIT {max_prefix_rows}
            """,
            placeholders={
                "elements_per_actor_query": self._elements_per_actor_query(),
                "max_prefix_rows": ast.Constant(value=MAX_PREFIX_ROWS),
            },
        )

    def _to_path_item(self, item: tuple[str, str]) -> PathsV2Item | None:
        event, label = item
        if event == PATHS_V2_OTHER:
            return None
        for source in self.step_sources:
            if source.event == event:
                return PathsV2Item(event=event, label=label if source.namingProperty is not None else None)
        return PathsV2Item(event=event, label=label)

    def _to_prefixes(self, rows: list[tuple[Any, ...]]) -> list[PathsV2Prefix]:
        prefixes: list[PathsV2Prefix] = []
        for prefix_items, actor_count in rows:
            items: list[PathsV2Item] = []
            for raw_item in prefix_items:
                item = self._to_path_item(raw_item)
                # Raw sequence items always name a real path item, never the other bucket.
                assert item is not None
                items.append(item)
            prefixes.append(PathsV2Prefix(items=items, count=actor_count))
        return prefixes

    def _to_results(self, rows: list[tuple[Any, ...]], prefixes: list[PathsV2Prefix]) -> PathsV2Results:
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

        return PathsV2Results(steps=[steps[index] for index in sorted(steps)], edges=edges, prefixes=prefixes)

    def _execute(self, query: ast.SelectQuery | ast.SelectSetQuery) -> Any:
        return execute_hogql_query(
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

    def _calculate(self) -> PathsV2QueryResponse:
        query = self.to_query()
        # Display-only response HogQL (never executed); bypass warehouse ACL so printing doesn't fail closed userless.
        hogql = to_printed_hogql(query, self.team, bypass_warehouse_access_control=True)

        response = self._execute(query)
        assert response.results is not None

        prefixes: list[PathsV2Prefix] = []
        if self.is_anchored:
            # A second aggregation over the same anchored sequences: the grid carries positional
            # counts, this carries the per-chain counts the hover preview reads.
            prefix_response = self._execute(self._anchored_prefix_counts_query())
            assert prefix_response.results is not None
            prefixes = self._to_prefixes(prefix_response.results)

        return PathsV2QueryResponse(
            results=self._to_results(response.results, prefixes),
            timings=response.timings,
            hogql=hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
