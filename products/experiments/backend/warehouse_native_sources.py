from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.hogql.direct_connection import get_direct_connection_source_none_or_raise
from posthog.hogql.direct_sql.capability import bigquery_direct_query_enabled

from posthog.models.team.team import Team
from posthog.models.user import User

from products.experiments.backend.metric_resolution import metric_dict_source_nodes
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

WAREHOUSE_NATIVE_NODE_KIND = "ExperimentWarehouseNativeNode"
WAREHOUSE_NATIVE_EXPOSURE_KIND = "ExperimentWarehouseNativeExposureConfig"


def warehouse_native_exposure_config(exposure_criteria: dict[str, Any] | None) -> dict[str, Any] | None:
    exposure_config = (exposure_criteria or {}).get("exposure_config")
    if isinstance(exposure_config, dict) and exposure_config.get("kind") == WAREHOUSE_NATIVE_EXPOSURE_KIND:
        return exposure_config
    return None


def validate_experiment_warehouse_native_sources(
    *, exposure_criteria: dict[str, Any] | None, metrics: list[dict[str, Any]], team: Team, user: Any
) -> None:
    """An experiment reads one kind of data: PostHog events, or the customer's warehouse through one
    connection. A warehouse-native exposure needs warehouse-native metrics, because nothing can join
    warehouse ids to PostHog persons."""
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
    validate_warehouse_native_sources(sources, team=team, user=user)


def validate_metric_warehouse_native_sources(metrics: list[dict[str, Any]], *, team: Team, user: Any) -> None:
    """The check for a metric saved on its own, such as a shared metric."""
    nodes = _metric_source_nodes(metrics)
    native_nodes = [node for node in nodes if node.get("kind") == WAREHOUSE_NATIVE_NODE_KIND]
    if native_nodes and len(native_nodes) < len(nodes):
        raise ValidationError(
            "A metric cannot mix a warehouse-native source with PostHog events or synced warehouse tables."
        )
    validate_warehouse_native_sources(native_nodes, team=team, user=user)


def validate_warehouse_native_sources(sources: list[dict[str, Any]], *, team: Team, user: Any) -> None:
    """Every source must name the same direct BigQuery connection, readable by the saving user, and the
    same unit binding. `sources` holds exposure configs and metric nodes; both carry `connection_id` and
    `unit`."""
    if not sources:
        return
    if not bigquery_direct_query_enabled(team):
        raise ValidationError("Warehouse-native sources are not available in this project.")

    connection_ids = {str(source.get("connection_id") or "") for source in sources}
    if len(connection_ids) > 1:
        raise ValidationError("All warehouse-native sources on an experiment must use the same connection.")
    unit_bindings = {_unit_binding_key(source) for source in sources}
    if len(unit_bindings) > 1:
        raise ValidationError(
            "All warehouse-native sources on an experiment must use the same unit binding (unit_type and id_namespace)."
        )

    # A synthetic principal or a userless caller has no access control to check, as in validate_warehouse_metrics.
    connection = get_direct_connection_source_none_or_raise(
        team,
        connection_ids.pop(),
        user=user if isinstance(user, User) else None,
        error_factory=ValidationError,
        require_pure_direct=True,
    )
    if connection is None:
        raise ValidationError("Warehouse-native sources need a connection_id.")
    if connection.source_type != ExternalDataSourceType.BIGQUERY:
        raise ValidationError("Warehouse-native sources support BigQuery connections only.")


def _metric_source_nodes(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        node
        for metric in metrics
        if isinstance(metric, dict)
        for node in metric_dict_source_nodes(metric)
        if isinstance(node, dict)
    ]


def _unit_binding_key(source: dict[str, Any]) -> tuple[str, str]:
    unit = source.get("unit")
    if not isinstance(unit, dict):
        return ("", "")
    return (str(unit.get("unit_type") or ""), str(unit.get("id_namespace") or ""))
