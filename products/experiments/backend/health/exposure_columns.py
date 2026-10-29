import pydantic

from posthog.schema import EventPropertyFilter, GroupPropertyFilter, PersonPropertyFilter, PersonsOnEventsMode

from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.property import GROUP_KEY_PROPERTY

from posthog.clickhouse.materialized_columns import get_materialized_column_for_property
from posthog.exceptions_capture import capture_exception
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.models.materialized_column_slots import MaterializedColumnSlot, MaterializedColumnSlotState

from products.experiments.backend.health.context import ExposureFilterPropertyType, ExposureFilterWithoutColumn
from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.hogql_queries.exposure_query_logic import normalize_to_exposure_criteria
from products.experiments.backend.hogql_queries.precompute_policy import team_precompute_skip_reason
from products.experiments.backend.metric_calculation.config import team_experiments_configs
from products.experiments.backend.models.experiment import Experiment

# The modes that read person properties from the events table. The other modes join the persons table.
_PERSON_PROPERTIES_ON_EVENTS = frozenset(
    {
        PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
        PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
    }
)


def load_exposure_filters_without_column(experiment: Experiment) -> tuple[ExposureFilterWithoutColumn, ...] | None:
    """The properties that each metric's query reads to apply the exposure filters and that ClickHouse keeps in no
    column of their own, in the order of the filters. Empty when the metric queries read precomputed exposures. None
    when the criteria don't parse or the lookup fails. Never raises."""
    try:
        return _filters_without_column(experiment)
    except Exception as error:
        capture_exception(error)
        return None


def _filters_without_column(experiment: Experiment) -> tuple[ExposureFilterWithoutColumn, ...] | None:
    try:
        criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    except pydantic.ValidationError:
        return None
    # The configs that the exposure query builds from, so the filters read here are the ones it applies.
    params = get_exposure_config_params_for_builder(criteria, experiment.team, experiment.start_date)
    filters = [
        prop
        for source in (params.exposure_config, params.activation_config)
        if source
        for prop in source.properties or []
    ]
    if not filters or _reads_precomputed_exposures(experiment):
        return ()
    modifiers = create_default_modifiers_for_team(experiment.team)
    # Each property of the native events table is a subcolumn of its own.
    events_have_subcolumns = use_new_events_schema(experiment.team_id, modifiers)
    person_properties_on_events = modifiers.personsOnEventsMode in _PERSON_PROPERTIES_ON_EVENTS
    without_column: dict[ExposureFilterWithoutColumn, None] = {}
    for prop in filters:
        property_type: ExposureFilterPropertyType
        match prop:
            case EventPropertyFilter(key=key):
                has_column = (
                    events_have_subcolumns
                    # HogQL computes a `$virt` property from other fields, so no column of its own can exist.
                    or key.startswith("$virt")
                    or get_materialized_column_for_property("events", "properties", key) is not None
                    or _has_dynamic_column(experiment, key)
                )
                property_type = "event"
            case PersonPropertyFilter(key=key):
                if key == "distinct_id":
                    has_column = True
                elif person_properties_on_events:
                    has_column = (
                        events_have_subcolumns
                        or get_materialized_column_for_property("events", "person_properties", key) is not None
                    )
                else:
                    has_column = get_materialized_column_for_property("person", "properties", key) is not None
                property_type = "person"
            case GroupPropertyFilter(key=key):
                # The exposure query joins the groups table for a group property, also with person properties on events.
                # It reads the group key and a `$virt` property from columns of that table.
                has_column = (
                    key == GROUP_KEY_PROPERTY
                    or key.startswith("$virt_")
                    or get_materialized_column_for_property("groups", "group_properties", key) is not None
                )
                property_type = "group"
            case _:
                continue
        if not has_column:
            without_column[ExposureFilterWithoutColumn(type=property_type, key=key)] = None
    return tuple(without_column)


def _reads_precomputed_exposures(experiment: Experiment) -> bool:
    """Whether the metric queries read the exposures from a table that a separate query fills, which applies the
    exposure filters once. It follows the precompute rules of `ExperimentQueryRunner`, without a metric's cohorts.

    When that query fails, the metric queries read the events, but the stored failure doesn't say which way they read,
    so the answer assumes the table."""
    if experiment.feature_flag.aggregation_group_type_index is not None:
        return False
    config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    return team_precompute_skip_reason(experiment.team, config, experiment, experiment.exposure_criteria) is None


def _has_dynamic_column(experiment: Experiment, key: str) -> bool:
    """Whether the team has a column of its own for the event property, which HogQL reads in place of the properties."""
    return MaterializedColumnSlot.objects.filter(
        team_id=experiment.team_id,
        state=MaterializedColumnSlotState.READY,
        property_definition__name=key,
    ).exists()
