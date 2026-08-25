from posthog.schema import (
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelsFilter,
    FunnelsQuery,
    HogQLPropertyFilter,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    PathsV2StepSource,
    StepOrderValue,
)

from posthog.hogql import ast

from posthog.models.team.team import Team

from products.product_analytics.backend.hogql_queries.paths_v2.path_item import (
    DEFAULT_CONVERSION_WINDOW_INTERVAL,
    DEFAULT_CONVERSION_WINDOW_INTERVAL_UNIT,
    DEFAULT_GAP_INTERVAL,
    DEFAULT_GAP_INTERVAL_UNIT,
    PATHS_V2_OTHER,
    item_label,
    item_tuple_expr,
    item_universe_filter_expr,
    path_item_expr,
    resolve_cleaning_rules,
    resolve_step_sources,
    source_label_expr,
    step_source_for_event,
)


def _step_node(item: PathsV2Item, source: PathsV2StepSource, cleaning_rules: list[tuple[str, str]]) -> EventsNode:
    """A funnel step matching exactly the events that derive into this path item."""
    if source.namingProperty is None:
        return EventsNode(event=item.event)
    label_matches = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=source_label_expr(source, cleaning_rules),
        right=ast.Constant(value=item_label(item, source)),
    )
    return EventsNode(event=item.event, properties=[HogQLPropertyFilter(key=label_matches.to_hogql())])


def _item_strict_exclusion(
    query: PathsV2Query,
    sources: list[PathsV2StepSource],
    segment_item_exprs: list[ast.Expr],
    cleaning_rules: list[tuple[str, str]],
    to_step: int,
) -> FunnelExclusionEventsNode:
    """The item-strict universe as one all-events exclusion spanning the whole segment: an event
    breaks the funnel iff it is part of the item universe (a step source's event, not an excluded
    item) and its derived item is not one of the segment's own items. Events outside the universe
    stay invisible, exactly as in the paths runner. Active from the first step through `to_step`
    (the last), so any intervening included item between any two consecutive segment steps
    disqualifies that attempt."""
    item_expr = path_item_expr(sources, cleaning_rules)
    not_a_segment_item = ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=item_expr,
        right=ast.Tuple(exprs=segment_item_exprs),
    )
    universe = ast.And(exprs=[item_universe_filter_expr(sources, query.pathsV2Filter, item_expr), not_a_segment_item])
    return FunnelExclusionEventsNode(
        event=None,
        funnelFromStep=0,
        funnelToStep=to_step,
        properties=[HogQLPropertyFilter(key=universe.to_hogql())],
    )


def _ensure_convertible(item: PathsV2Item | None, endpoint: str) -> PathsV2Item:
    if item is None or item.event == PATHS_V2_OTHER:
        raise ValueError(
            f"The edge {endpoint} is not a named path item; the other row and drop-offs have no funnel equivalent."
        )
    return item


def segment_to_funnels_query(
    query: PathsV2Query,
    team: Team,
    items: list[PathsV2Item | None],
    window_interval: int,
    window_interval_unit: FunnelConversionWindowTimeUnit,
) -> FunnelsQuery:
    """Convert a displayed segment of named path items into the funnel that reproduces its
    unique-actor count exactly: an ordered funnel over the same date range and properties, with the
    given conversion window and the item-strict universe as one all-events exclusion spanning every
    step. The items are in funnel (forward-time) order; anchored segments pass window W, open-mode
    single edges pass gap G."""
    if len(items) < 2:
        raise ValueError("A segment needs at least two path items to convert to a funnel.")

    convertible = [_ensure_convertible(item, f"step {index}") for index, item in enumerate(items)]
    sources = resolve_step_sources(query)
    cleaning_rules = resolve_cleaning_rules(query.pathsV2Filter, team)
    item_sources = [step_source_for_event(sources, item.event) for item in convertible]

    seen: set[tuple[str, str]] = set()
    segment_item_exprs: list[ast.Expr] = []
    for item, source in zip(convertible, item_sources):
        key = (item.event, item_label(item, source))
        if key not in seen:
            seen.add(key)
            segment_item_exprs.append(item_tuple_expr(item, source))

    return FunnelsQuery(
        series=[_step_node(item, source, cleaning_rules) for item, source in zip(convertible, item_sources)],
        funnelsFilter=FunnelsFilter(
            exclusions=[
                _item_strict_exclusion(query, sources, segment_item_exprs, cleaning_rules, to_step=len(convertible) - 1)
            ],
            funnelOrderType=StepOrderValue.ORDERED,
            funnelWindowInterval=window_interval,
            funnelWindowIntervalUnit=window_interval_unit,
        ),
        dateRange=query.dateRange,
        properties=query.properties,
        filterTestAccounts=query.filterTestAccounts,
    )


def edge_to_funnels_query(
    query: PathsV2Query,
    team: Team,
    source_item: PathsV2Item | None,
    target_item: PathsV2Item | None,
) -> FunnelsQuery:
    """Convert an open-mode edge between two named path items into the funnel that reproduces its
    position-free unique-actor count: an ordered two-step funnel with the gap G as conversion window
    and the item-strict universe as an all-events exclusion between the steps."""
    paths_filter = query.pathsV2Filter or PathsV2Filter()
    gap_interval = paths_filter.gapInterval if paths_filter.gapInterval is not None else DEFAULT_GAP_INTERVAL
    gap_interval_unit: FunnelConversionWindowTimeUnit = (
        paths_filter.gapIntervalUnit if paths_filter.gapIntervalUnit is not None else DEFAULT_GAP_INTERVAL_UNIT
    )
    return segment_to_funnels_query(query, team, [source_item, target_item], gap_interval, gap_interval_unit)


def anchored_segment_to_funnels_query(query: PathsV2Query, team: Team, items: list[PathsV2Item | None]) -> FunnelsQuery:
    """Convert an anchored-mode segment (any depth) into its funnel, reading window W from the query.
    Anchored mode's promise: every displayed segment equals this plain funnel with window W."""
    paths_filter = query.pathsV2Filter or PathsV2Filter()
    window_interval = (
        paths_filter.conversionWindowInterval
        if paths_filter.conversionWindowInterval is not None
        else DEFAULT_CONVERSION_WINDOW_INTERVAL
    )
    window_interval_unit: FunnelConversionWindowTimeUnit = (
        paths_filter.conversionWindowIntervalUnit
        if paths_filter.conversionWindowIntervalUnit is not None
        else DEFAULT_CONVERSION_WINDOW_INTERVAL_UNIT
    )
    return segment_to_funnels_query(query, team, items, window_interval, window_interval_unit)
