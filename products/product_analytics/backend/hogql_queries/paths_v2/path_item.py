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
    paths_filter = paths_filter or PathsV2Filter()
    apply_team = paths_filter.applyTeamPathCleaning
    if apply_team is None:
        apply_team = DEFAULT_APPLY_TEAM_PATH_CLEANING
    # team.path_cleaning_filters is a nullable JSONField; path_cleaning_filter_models() iterates it
    # unguarded, so the truthiness check doubles as the None guard.
    team_rules = team.path_cleaning_filter_models() if apply_team and team.path_cleaning_filters else []
    local_rules = paths_filter.localPathCleaningFilters or []
    return [(rule.regex, rule.alias or "") for rule in [*team_rules, *local_rules] if rule.regex]


def _raw_source_label_expr(source: PathsV2StepSource) -> ast.Expr:
    """A source's label before cleaning: the naming property as a string, NULL both when the
    property is missing and for sources without a naming property."""
    if source.namingProperty is None:
        return ast.Constant(value=None)
    return ast.Call(name="toString", args=[ast.Field(chain=["properties", source.namingProperty])])


def _cleaned_label_expr(raw_label: ast.Expr, cleaning_rules: list[tuple[str, str]]) -> ast.Expr:
    """Apply the cleaning rules to a raw label and coalesce to ''. A NULL raw label stays NULL
    through every replaceRegexpAll, so cleaning cannot invent a label where none exists."""
    label = raw_label
    for regex, alias in cleaning_rules:
        label = ast.Call(name="replaceRegexpAll", args=[label, ast.Constant(value=regex), ast.Constant(value=alias)])
    return ast.Call(name="ifNull", args=[label, ast.Constant(value="")])


def source_label_expr(source: PathsV2StepSource, cleaning_rules: list[tuple[str, str]]) -> ast.Expr:
    """Label of a path item produced by this source: the naming property value after path cleaning,
    coalesced to '' when the property is missing. Constant '' for sources without a naming property,
    where the event alone identifies the item."""
    if source.namingProperty is None:
        return ast.Constant(value="")
    return _cleaned_label_expr(_raw_source_label_expr(source), cleaning_rules)


def path_item_expr(sources: list[PathsV2StepSource], cleaning_rules: list[tuple[str, str]]) -> ast.Expr:
    """Identity of the path item an event produces: tuple(event, label).

    The runner groups journeys by this expression and the funnel converter reuses it verbatim in
    step filters and the item-strict exclusion, so both sides derive identical items by construction.
    The cleaning chain applies once to the multiIf-selected raw label, so the expression grows with
    sources plus rules rather than sources times rules.
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
        label_args.append(_raw_source_label_expr(source))
    label_args.append(ast.Constant(value=None))
    raw_label = ast.Call(name="multiIf", args=label_args)
    return ast.Tuple(exprs=[ast.Field(chain=["event"]), _cleaned_label_expr(raw_label, cleaning_rules)])


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
    for a source without a naming property is the item itself, and for a source with one is the item
    whose naming property is missing. Tuples no derivable item can equal are inert."""
    if paths_filter is None or not paths_filter.excludedItems:
        return []
    return [(item.event, item.label or "") for item in paths_filter.excludedItems]


def item_universe_filter_expr(
    sources: list[PathsV2StepSource], paths_filter: PathsV2Filter | None, item_expr: ast.Expr
) -> ast.Expr:
    """Whether an event is part of the item universe: its event matches a step source and its
    derived item is not excluded. The runner's event base and the converter's item-strict exclusion
    universe both come from here, so an excluded item is invisible to both sides by construction,
    exactly like an event outside the step sources."""
    universe: ast.Expr = source_events_filter_expr(sources)
    excluded = excluded_item_tuples(paths_filter)
    if not excluded:
        return universe
    not_excluded = ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=item_expr,
        right=ast.Tuple(
            exprs=[ast.Tuple(exprs=[ast.Constant(value=event), ast.Constant(value=label)]) for event, label in excluded]
        ),
    )
    return ast.And(exprs=[universe, not_excluded])
