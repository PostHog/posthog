from typing import cast

import pydantic

from posthog.schema import ActionsNode, ExperimentExposureCriteria

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.property_planner import PropertyAccessPlan, PropertyScope, PropertySourceKind, plan_property_access
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.property_types import build_property_swapper
from posthog.hogql.visitor import GetFieldsTraverser

from posthog.exceptions_capture import capture_exception
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.schema_enums import MaterializationMode

from products.experiments.backend.health.context import (
    ExposureFilterPropertyType,
    ExposureFilterSource,
    ExposureFilterWithoutColumn,
)
from products.experiments.backend.hogql_queries.base_query_utils import event_or_action_to_filter
from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    get_test_accounts_filter,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.models.experiment import Experiment

_FILTER_TYPES: dict[PropertyScope, ExposureFilterPropertyType] = {
    PropertyScope.EVENT: "event",
    PropertyScope.PERSON: "person",
    PropertyScope.GROUP: "group",
}
# The exposure query always reads the flag key, so a filter on it costs nothing more and removing it changes nothing.
_FLAG_KEY_PROPERTY = "$feature_flag"


def _reads_all_properties(plan: PropertyAccessPlan, context: HogQLContext) -> bool:
    if plan.source.kind != PropertySourceKind.JSON:
        return False
    # Before the lazy persons table expands, the planner can't match the columns of the `person` table.
    if plan.scope == PropertyScope.PERSON and plan.source.table_name is None:
        metadata = context.property_metadata
        return (
            metadata is None
            or context.modifiers.materializationMode == MaterializationMode.DISABLED
            or metadata.materialized_column("person", "properties", plan.property_name) is None
        )
    # The planner calls a read of the native events table JSON, but each property there is a subcolumn of its own.
    if plan.source.table_name == "events" and context.uses_new_events_schema():
        return False
    return True


def _named_properties(expr: ast.Expr) -> set[str | int]:
    """The properties that a filter names. A `$virt` property expands to reads of other properties when its type
    resolves, and the filter names none of those."""
    return {field.chain[-1] for field in GetFieldsTraverser(expr).fields if len(field.chain) > 1}


def _filters_without_column(
    experiment: Experiment, criteria: ExperimentExposureCriteria | None
) -> tuple[ExposureFilterWithoutColumn, ...]:
    team = experiment.team
    # The configs that the exposure query builds from, as the filters that it applies.
    params = get_exposure_config_params_for_builder(criteria, team, experiment.start_date)
    filters = [
        (
            event_or_action_to_filter(team, config),
            ExposureFilterSource.EXPOSURE_ACTION
            if isinstance(config, ActionsNode)
            else ExposureFilterSource.EXPOSURE_CRITERIA,
        )
        for config in (params.exposure_config, params.activation_config)
        if config
    ]
    filters += [(expr, ExposureFilterSource.TEST_ACCOUNTS) for expr in get_test_accounts_filter(team, criteria)]
    named_by_filter = [_named_properties(expr) for expr, _ in filters]
    if not any(named_by_filter):
        return ()
    modifiers = create_default_modifiers_for_team(team)
    # The runner resolves this modifier, and the catalog cache key includes it, so a health read shares the compile's entry.
    modifiers.useNewEventsSchema = use_new_events_schema(team.pk, modifiers)
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        database=Database.create_for(team=team, modifiers=modifiers, use_cached_sources=True),
        enable_select_queries=True,
        modifiers=modifiers,
    )
    query = ast.SelectQuery(
        select=[ast.Constant(value=1)],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(exprs=[expr for expr, _ in filters]),
    )
    resolved = resolve_types(query, context, dialect="clickhouse")
    build_property_swapper(resolved, context)
    where = cast(ast.And, resolved.where)

    found: dict[ExposureFilterWithoutColumn, None] = {}
    for expr, (_, source), named_keys in zip(where.exprs, filters, named_by_filter, strict=True):
        for field in GetFieldsTraverser(expr).fields:
            plan = plan_property_access(field, context)
            if plan is None or plan.property_name not in named_keys or plan.property_name == _FLAG_KEY_PROPERTY:
                continue
            filter_type = _FILTER_TYPES.get(plan.scope)
            if filter_type is not None and _reads_all_properties(plan, context):
                found[ExposureFilterWithoutColumn(type=filter_type, key=plan.property_name, source=source)] = None
    return tuple(found)


def load_filters_without_column(experiment: Experiment) -> tuple[ExposureFilterWithoutColumn, ...] | None:
    """The filters of a query that reads the exposures from the events, for each property that the query reads from the
    JSON of all the properties. None when the criteria don't parse or the lookup fails. Never raises."""
    try:
        criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    except pydantic.ValidationError:
        return None
    try:
        return _filters_without_column(experiment, criteria)
    except Exception as error:
        capture_exception(error)
        return None
