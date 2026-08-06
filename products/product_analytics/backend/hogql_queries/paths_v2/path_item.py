from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelConversionWindowTimeUnit, PathsV2Item, PathsV2Query, PathsV2StepSource

from posthog.hogql import ast
from posthog.hogql.property import apply_path_cleaning

from posthog.models.team.team import Team

# Sentinel event marking a per-step "other" bucket row; never a real event name.
PATHS_V2_OTHER = "$$__posthog_other__$$"

# Must match the @default annotations on PathsV2Filter in
# frontend/src/queries/schema/schema-general.ts; test_defaults pins them to the generated schema.
DEFAULT_MAX_STEPS = 5
DEFAULT_MAX_ROWS_PER_STEP = 3
DEFAULT_GAP_INTERVAL = 30
DEFAULT_GAP_INTERVAL_UNIT = FunnelConversionWindowTimeUnit.MINUTE
DEFAULT_COLLAPSE_REPEATS = True
DEFAULT_CONVERSION_WINDOW_INTERVAL = 30
DEFAULT_CONVERSION_WINDOW_INTERVAL_UNIT = FunnelConversionWindowTimeUnit.MINUTE


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


def item_label(item: PathsV2Item, source: PathsV2StepSource) -> str:
    """The label an item contributes to its `(event, label)` identity: the empty string for a source
    without a naming property (the event alone identifies the item), otherwise the item's label,
    which must be present."""
    if source.namingProperty is None:
        return ""
    if item.label is None:
        raise ValidationError(f"Path item for event {item.event!r} needs a label, as its source has a naming property.")
    return item.label


def item_tuple_expr(item: PathsV2Item, source: PathsV2StepSource) -> ast.Expr:
    """Constant `(event, label)` identity of a concrete path item, matching `path_item_expr`'s shape
    so the runner can compare a derived item against a chosen anchor and the converter can name it."""
    return ast.Tuple(exprs=[ast.Constant(value=item.event), ast.Constant(value=item_label(item, source))])
