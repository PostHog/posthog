from typing import cast

import pydantic

from posthog.schema import EventPropertyFilter, ExperimentExposureCriteria, GroupPropertyFilter, PersonPropertyFilter

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.property import property_to_expr
from posthog.hogql.property_planner import PropertyAccessPlan, PropertyScope, PropertySourceKind, plan_property_access
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.property_types import build_property_swapper
from posthog.hogql.visitor import TraversingVisitor

from posthog.exceptions_capture import capture_exception

from products.experiments.backend.health.context import (
    ExposureFilterPropertyType,
    ExposureFilterWithoutColumn,
    ExposureReads,
)
from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    get_test_accounts_filter,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.hogql_queries.precompute_policy import team_precompute_skip_reason
from products.experiments.backend.metric_calculation.config import team_experiments_configs
from products.experiments.backend.models.experiment import Experiment

_FILTER_TYPES: dict[PropertyScope, ExposureFilterPropertyType] = {
    PropertyScope.EVENT: "event",
    PropertyScope.PERSON: "person",
    PropertyScope.GROUP: "group",
}
# The exposure query always reads the flag key, so a filter on it costs nothing more and removing it changes nothing.
_FLAG_KEY_PROPERTY = "$feature_flag"


class _PropertyFields(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.fields: list[ast.Field] = []

    def visit_field(self, node: ast.Field) -> None:
        self.fields.append(node)


def load_exposure_reads(experiment: Experiment) -> ExposureReads | None:
    """How the metric queries read the exposures, with the filters that a read of the events would apply. None when the
    criteria don't parse or the lookup fails. Never raises."""
    try:
        criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    except pydantic.ValidationError:
        return None
    try:
        return ExposureReads(
            precomputed=_precomputes_exposures(experiment),
            filters_without_column=_filters_without_column(experiment, criteria),
        )
    except Exception as error:
        capture_exception(error)
        return None


def _precomputes_exposures(experiment: Experiment) -> bool:
    """Whether a metric query on events reads the exposures from the table that a separate query fills, which applies
    the exposure filters once. It follows the rules of `ExperimentQueryRunner`, without a metric's cohorts."""
    if experiment.feature_flag.aggregation_group_type_index is not None:
        return False
    config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    return team_precompute_skip_reason(experiment.team, config, experiment, experiment.exposure_criteria) is None


def _filters_without_column(
    experiment: Experiment, criteria: ExperimentExposureCriteria | None
) -> tuple[ExposureFilterWithoutColumn, ...]:
    team = experiment.team
    # The configs that the exposure query builds from, so the filters read here are the ones it applies.
    params = get_exposure_config_params_for_builder(criteria, team, experiment.start_date)
    properties = [
        prop
        for source in (params.exposure_config, params.activation_config)
        if source
        for prop in source.properties or []
        if isinstance(prop, EventPropertyFilter | PersonPropertyFilter | GroupPropertyFilter)
    ]
    exposure_filters = [property_to_expr(prop, team) for prop in properties]
    test_account_filters = get_test_accounts_filter(team, criteria)
    if not exposure_filters and not test_account_filters:
        return ()
    # A `$virt` property expands to reads of other properties, which no filter names.
    named_keys = {prop.key for prop in properties}
    if test_account_filters:
        named_keys |= {prop.get("key") for prop in team.test_account_filters}
    modifiers = create_default_modifiers_for_team(team)
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        database=Database.create_for_posthog_tables(team, modifiers=modifiers),
        enable_select_queries=True,
        modifiers=modifiers,
    )
    query = ast.SelectQuery(
        select=[ast.Constant(value=1)],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(exprs=[*exposure_filters, *test_account_filters]),
    )
    resolved = resolve_types(query, context, dialect="clickhouse")
    build_property_swapper(resolved, context)
    where = cast(ast.And, resolved.where)

    found: dict[tuple[ExposureFilterPropertyType, str], ExposureFilterWithoutColumn] = {}
    for index, expr in enumerate(where.exprs):
        visitor = _PropertyFields()
        visitor.visit(expr)
        for field in visitor.fields:
            plan = plan_property_access(field, context)
            if plan is None or plan.property_name not in named_keys or plan.property_name == _FLAG_KEY_PROPERTY:
                continue
            filter_type = _FILTER_TYPES.get(plan.scope)
            if filter_type is not None and _reads_all_properties(plan, context):
                found.setdefault(
                    (filter_type, plan.property_name),
                    ExposureFilterWithoutColumn(
                        type=filter_type, key=plan.property_name, test_account=index >= len(exposure_filters)
                    ),
                )
    return tuple(found.values())


def _reads_all_properties(plan: PropertyAccessPlan, context: HogQLContext) -> bool:
    if plan.source.kind != PropertySourceKind.JSON:
        return False
    # Before the lazy persons table expands, the planner can't match the columns of the `person` table.
    if plan.scope == PropertyScope.PERSON and plan.source.table_name is None:
        metadata = context.property_metadata
        return metadata is None or metadata.materialized_column("person", "properties", plan.property_name) is None
    # The planner calls a read of the native events table JSON, but each property there is a subcolumn of its own.
    if plan.source.table_name == "events" and context.uses_new_events_schema():
        return False
    return True
