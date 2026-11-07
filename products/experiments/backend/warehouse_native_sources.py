from typing import Any

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.hogql.direct_connection import (
    RAW_QUERY_TABLE_DENIED_ERROR,
    get_direct_connection_source_none_or_raise,
    raw_query_denied_by_table_access,
)
from posthog.hogql.direct_sql.capability import bigquery_direct_query_enabled

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.experiments.backend.metric_resolution import (
    metric_dict_source_nodes,
    metric_dict_uses_warehouse_native_source,
)
from products.experiments.backend.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

WAREHOUSE_NATIVE_NODE_KIND = "ExperimentWarehouseNativeNode"
WAREHOUSE_NATIVE_EXPOSURE_KIND = "ExperimentWarehouseNativeExposureConfig"


@frozen
class UnitBinding:
    unit_type: str
    id_namespace: str


def warehouse_native_exposure_config(exposure_criteria: dict[str, Any] | None) -> dict[str, Any] | None:
    exposure_config = (exposure_criteria or {}).get("exposure_config")
    if isinstance(exposure_config, dict) and exposure_config.get("kind") == WAREHOUSE_NATIVE_EXPOSURE_KIND:
        return exposure_config
    return None


def validate_experiment_warehouse_native_sources(
    *,
    exposure_criteria: dict[str, Any] | None,
    metrics: list[dict[str, Any]],
    team: Team,
    user: Any,
    resolve_connection: bool = True,
) -> str | None:
    """An experiment reads one kind of data: PostHog events, or the customer's warehouse through one
    connection. A warehouse-native exposure needs warehouse-native metrics, because nothing can join
    warehouse ids to PostHog persons. Returns the connection id of the warehouse-native sources, if any.
    A caller that checks several experiments on one connection resolves it once, with `resolve_connection`
    off."""
    exposure_config = warehouse_native_exposure_config(exposure_criteria)
    nodes = _metric_source_nodes(metrics)
    native_nodes = [node for node in nodes if node.get("kind") == WAREHOUSE_NATIVE_NODE_KIND]
    if exposure_config is None and native_nodes:
        raise ValidationError(
            "A warehouse-native metric needs a warehouse-native exposure. "
            "Set exposure_criteria.exposure_config to a query on the same connection."
        )
    if exposure_config is not None and len(native_nodes) < len(nodes):
        raise ValidationError(
            "An experiment with a warehouse-native exposure can only use warehouse-native metrics. "
            "Remove the metrics that read PostHog events or synced warehouse tables."
        )
    sources = [exposure_config, *native_nodes] if exposure_config is not None else native_nodes
    connection_id = warehouse_native_sources_agree(sources)
    if connection_id is not None and resolve_connection:
        validate_warehouse_native_connection(connection_id, team=team, user=user)
    return connection_id


def validate_metric_warehouse_native_sources(metrics: list[dict[str, Any]], *, team: Team, user: Any) -> None:
    """The check for a metric saved on its own, such as a shared metric."""
    nodes = _metric_source_nodes(metrics)
    native_nodes = [node for node in nodes if node.get("kind") == WAREHOUSE_NATIVE_NODE_KIND]
    if native_nodes and len(native_nodes) < len(nodes):
        raise ValidationError(
            "A metric cannot mix a warehouse-native source with PostHog events or synced warehouse tables."
        )
    connection_id = warehouse_native_sources_agree(native_nodes)
    if connection_id is not None:
        validate_warehouse_native_connection(connection_id, team=team, user=user)


def warehouse_native_sources_agree(sources: list[dict[str, Any]]) -> str | None:
    """Every source must name the same connection and the same unit binding. `sources` holds exposure
    configs and metric nodes; both carry `connection_id` and `unit`. Returns the shared connection id."""
    if not sources:
        return None
    connection_ids = {str(source.get("connection_id") or "") for source in sources}
    if len(connection_ids) > 1:
        raise ValidationError("All warehouse-native sources on an experiment must use the same connection.")
    unit_bindings = {_unit_binding(source) for source in sources}
    if len(unit_bindings) > 1:
        raise ValidationError(
            "All warehouse-native sources on an experiment must use the same unit binding (unit_type and id_namespace)."
        )
    return connection_ids.pop()


def validate_warehouse_native_connection(connection_id: str, *, team: Team, user: Any) -> None:
    """The connection must be a direct BigQuery source that the saving user can read in full."""
    if not bigquery_direct_query_enabled(team):
        raise ValidationError("Warehouse-native sources are not available in this project.")

    # A synthetic principal or a userless caller has no access control to check, as in validate_warehouse_metrics.
    connection = get_direct_connection_source_none_or_raise(
        team,
        connection_id,
        user=user if isinstance(user, User) else None,
        error_factory=ValidationError,
        require_pure_direct=True,
    )
    if connection is None:
        raise ValidationError("Warehouse-native sources need a connection_id.")
    if connection.source_type != ExternalDataSourceType.BIGQUERY:
        raise ValidationError("Warehouse-native sources support BigQuery connections only.")
    # The queries are raw SQL, which the runner cannot check table by table, so the same rule as the raw
    # query path applies: the user must be able to read every table on the connection.
    if isinstance(user, User) and raw_query_denied_by_table_access(team, connection, user=user):
        raise PermissionDenied(RAW_QUERY_TABLE_DENIED_ERROR)


def validate_saved_metric_query_against_linked_experiments(
    saved_metric: ExperimentSavedMetric, query: dict[str, Any], *, team: Team, user: Any
) -> None:
    """Every experiment that links the shared metric reads the new query on its next calculation, so the
    query has to fit each of them."""
    if not metric_dict_uses_warehouse_native_source(query) and not metric_dict_uses_warehouse_native_source(
        saved_metric.query or {}
    ):
        return
    links = (
        ExperimentToSavedMetric.objects.filter(saved_metric=saved_metric, experiment__team_id=team.id)
        .exclude(experiment__deleted=True)
        .select_related("experiment")
        .prefetch_related("experiment__experimenttosavedmetric_set__saved_metric")
    )
    connection_ids: set[str] = set()
    for link in links:
        experiment = link.experiment
        other_queries = [
            other.saved_metric.query
            for other in experiment.experimenttosavedmetric_set.all()
            if other.saved_metric_id != saved_metric.id and other.saved_metric.query
        ]
        try:
            connection_id = validate_experiment_warehouse_native_sources(
                exposure_criteria=experiment.exposure_criteria,
                metrics=[*(experiment.metrics or []), *(experiment.metrics_secondary or []), *other_queries, query],
                team=team,
                user=user,
                resolve_connection=False,
            )
        except ValidationError as error:
            # The user may not be allowed to see the experiment, so the error does not name it.
            detail = error.detail[0] if isinstance(error.detail, list) else error.detail
            raise ValidationError(f"A linked experiment uses this metric. {detail}")
        if connection_id is not None:
            connection_ids.add(connection_id)
    for connection_id in sorted(connection_ids):
        validate_warehouse_native_connection(connection_id, team=team, user=user)


def _metric_source_nodes(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        node
        for metric in metrics
        if isinstance(metric, dict)
        for node in metric_dict_source_nodes(metric)
        if isinstance(node, dict)
    ]


def _unit_binding(source: dict[str, Any]) -> UnitBinding:
    unit = source.get("unit")
    if not isinstance(unit, dict):
        return UnitBinding(unit_type="", id_namespace="")
    return UnitBinding(unit_type=str(unit.get("unit_type") or ""), id_namespace=str(unit.get("id_namespace") or ""))
