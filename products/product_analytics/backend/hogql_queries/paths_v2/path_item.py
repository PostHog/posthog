from rest_framework.exceptions import ValidationError

from posthog.schema import PathsV2Query, PathsV2StepSource

from posthog.hogql import ast
from posthog.hogql.property import apply_path_cleaning

from posthog.models.team.team import Team


def default_step_sources() -> list[PathsV2StepSource]:
    """The pageviews preset: `$pageview` named by the cleaned URL path."""
    return [PathsV2StepSource(event="$pageview", namingProperty="$pathname")]


def resolve_step_sources(query: PathsV2Query) -> list[PathsV2StepSource]:
    if query.pathsV2Filter is None or query.pathsV2Filter.stepSources is None:
        return default_step_sources()
    return query.pathsV2Filter.stepSources


def step_source_for_event(sources: list[PathsV2StepSource], event: str) -> PathsV2StepSource:
    for source in sources:
        if source.event == event:
            return source
    raise ValidationError(f"No step source is defined for event {event!r}.")


def source_label_expr(source: PathsV2StepSource, team: Team) -> ast.Expr:
    """Label of a path item produced by this source: the naming property value after team path
    cleaning, coalesced to '' when the property is missing. Constant '' for sources without a
    naming property, where the event alone identifies the item."""
    if source.namingProperty is None:
        return ast.Constant(value="")
    raw_value = ast.Call(name="toString", args=[ast.Field(chain=["properties", source.namingProperty])])
    return ast.Call(name="ifNull", args=[apply_path_cleaning(raw_value, team), ast.Constant(value="")])


def path_item_expr(sources: list[PathsV2StepSource], team: Team) -> ast.Expr:
    """Identity of the path item an event produces: tuple(event, label).

    The runner groups journeys by this expression and the funnel converter reuses it verbatim in
    step filters and the item-strict exclusion, so both sides derive identical items by construction.
    """
    label_args: list[ast.Expr] = []
    for source in sources:
        label_args.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=source.event),
            )
        )
        label_args.append(source_label_expr(source, team))
    label_args.append(ast.Constant(value=""))
    return ast.Tuple(exprs=[ast.Field(chain=["event"]), ast.Call(name="multiIf", args=label_args)])


def source_events_filter_expr(sources: list[PathsV2StepSource]) -> ast.Expr:
    """`event IN (...)`: whether an event can become a path item at all."""
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Constant(value=[source.event for source in sources]),
    )
