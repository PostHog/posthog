from rest_framework.exceptions import ValidationError

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
    path_item_expr,
    resolve_step_sources,
    source_events_filter_expr,
    source_label_expr,
    step_source_for_event,
)


def _item_label(item: PathsV2Item, source: PathsV2StepSource) -> str:
    if source.namingProperty is None:
        return ""
    if item.label is None:
        raise ValidationError(f"Path item for event {item.event!r} needs a label, as its source has a naming property.")
    return item.label


def _item_tuple_expr(item: PathsV2Item, source: PathsV2StepSource) -> ast.Expr:
    return ast.Tuple(exprs=[ast.Constant(value=item.event), ast.Constant(value=_item_label(item, source))])


def _step_node(item: PathsV2Item, source: PathsV2StepSource, team: Team) -> EventsNode:
    """A funnel step matching exactly the events that derive into this path item."""
    if source.namingProperty is None:
        return EventsNode(event=item.event)
    label_matches = ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=source_label_expr(source, team),
        right=ast.Constant(value=_item_label(item, source)),
    )
    return EventsNode(event=item.event, properties=[HogQLPropertyFilter(key=label_matches.to_hogql())])


def _item_strict_exclusion(
    sources: list[PathsV2StepSource],
    segment_item_exprs: list[ast.Expr],
    team: Team,
) -> FunnelExclusionEventsNode:
    """The item-strict universe as one all-events exclusion: an event breaks the funnel iff it is
    an included path item whose derived item is not one of the segment's own items. Events outside
    the step sources stay invisible, exactly as in the paths runner."""
    not_a_segment_item = ast.And(
        exprs=[
            ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=path_item_expr(sources, team), right=item_expr)
            for item_expr in segment_item_exprs
        ]
    )
    universe = ast.And(exprs=[source_events_filter_expr(sources), not_a_segment_item])
    return FunnelExclusionEventsNode(
        event=None,
        funnelFromStep=0,
        funnelToStep=1,
        properties=[HogQLPropertyFilter(key=universe.to_hogql())],
    )


def edge_to_funnels_query(
    query: PathsV2Query,
    team: Team,
    source_item: PathsV2Item,
    target_item: PathsV2Item,
) -> FunnelsQuery:
    """Convert a displayed edge into the funnel that reproduces its unique-actor count: an ordered
    two-step funnel over the same date range and properties, with the gap G as conversion window
    and the item-strict universe encoded as an all-events exclusion between the steps."""
    paths_filter = query.pathsV2Filter or PathsV2Filter()
    sources = resolve_step_sources(query)

    source_source = step_source_for_event(sources, source_item.event)
    target_source = step_source_for_event(sources, target_item.event)

    segment_item_exprs = [_item_tuple_expr(source_item, source_source)]
    if (target_item.event, _item_label(target_item, target_source)) != (
        source_item.event,
        _item_label(source_item, source_source),
    ):
        segment_item_exprs.append(_item_tuple_expr(target_item, target_source))

    gap_interval = (
        paths_filter.gapInterval
        if paths_filter.gapInterval is not None
        else PathsV2Filter.model_fields["gapInterval"].default
    )
    gap_interval_unit: FunnelConversionWindowTimeUnit = (
        paths_filter.gapIntervalUnit
        if paths_filter.gapIntervalUnit is not None
        else PathsV2Filter.model_fields["gapIntervalUnit"].default
    )

    return FunnelsQuery(
        series=[
            _step_node(source_item, source_source, team),
            _step_node(target_item, target_source, team),
        ],
        funnelsFilter=FunnelsFilter(
            exclusions=[_item_strict_exclusion(sources, segment_item_exprs, team)],
            funnelOrderType=StepOrderValue.ORDERED,
            funnelWindowInterval=gap_interval,
            funnelWindowIntervalUnit=gap_interval_unit,
        ),
        dateRange=query.dateRange,
        properties=query.properties,
        filterTestAccounts=query.filterTestAccounts,
    )
