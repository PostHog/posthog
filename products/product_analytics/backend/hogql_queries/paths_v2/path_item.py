from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelConversionWindowTimeUnit, PathsV2Filter, PathsV2Item, PathsV2Query, PathsV2StepSource

from posthog.hogql import ast

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
DEFAULT_APPLY_TEAM_PATH_CLEANING = True


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


def resolve_cleaning_rules(paths_filter: PathsV2Filter | None, team: Team) -> list[tuple[str, str]]:
    """The path cleaning rules in application order: the team's rules (unless disabled), then the
    insight-local rules. The runner and the funnel converter both resolve rules through here, so a
    displayed item and its funnel steps always clean labels identically. Rules without a regex have
    nothing to match and are skipped; a missing alias strips the match."""
    apply_team = paths_filter.applyTeamPathCleaning if paths_filter is not None else None
    team_rules = (
        team.path_cleaning_filter_models()
        if (apply_team if apply_team is not None else DEFAULT_APPLY_TEAM_PATH_CLEANING)
        else []
    )
    local_rules = paths_filter.localPathCleaningFilters or [] if paths_filter is not None else []
    return [(rule.regex, rule.alias or "") for rule in [*team_rules, *local_rules] if rule.regex]


def source_label_expr(source: PathsV2StepSource, cleaning_rules: list[tuple[str, str]]) -> ast.Expr:
    """Label of a path item produced by this source: the naming property value after path cleaning,
    coalesced to '' when the property is missing. Constant '' for sources without a naming property,
    where the event alone identifies the item."""
    if source.namingProperty is None:
        return ast.Constant(value="")
    label: ast.Expr = ast.Call(name="toString", args=[ast.Field(chain=["properties", source.namingProperty])])
    for regex, alias in cleaning_rules:
        label = ast.Call(name="replaceRegexpAll", args=[label, ast.Constant(value=regex), ast.Constant(value=alias)])
    return ast.Call(name="ifNull", args=[label, ast.Constant(value="")])


def path_item_expr(sources: list[PathsV2StepSource], cleaning_rules: list[tuple[str, str]]) -> ast.Expr:
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
        label_args.append(source_label_expr(source, cleaning_rules))
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


def excluded_item_tuples(paths_filter: PathsV2Filter | None) -> list[tuple[str, str]]:
    """The `(event, label)` identities of the excluded items. A missing label means '' here, which
    for a source without a naming property is the item itself; for a source with one, the label is
    required by validation, so '' only ever means the item whose naming property is missing."""
    if paths_filter is None or not paths_filter.excludedItems:
        return []
    return [(item.event, item.label or "") for item in paths_filter.excludedItems]


def excluded_items_filter_expr(item_expr: ast.Expr, excluded: list[tuple[str, str]]) -> ast.Expr | None:
    """Filter dropping events whose derived path item is excluded. The runner applies it to the
    event base and the converter to the item-strict exclusion universe, so an excluded item is
    invisible to both sides, exactly like an event outside the step sources."""
    if not excluded:
        return None
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=item_expr,
                right=ast.Tuple(exprs=[ast.Constant(value=event), ast.Constant(value=label)]),
            )
            for event, label in excluded
        ]
    )
