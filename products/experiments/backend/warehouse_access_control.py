from typing import Any

from rest_framework.exceptions import PermissionDenied

from posthog.hogql.database.database import Database

from posthog.models.team.team import Team
from posthog.models.user import User

from products.experiments.backend.metric_utils import collect_metric_warehouse_tables
from products.experiments.backend.warehouse_timestamp_validation import enforce_warehouse_metric_timestamp_types


def validate_warehouse_metrics(metrics: list[dict[str, Any]], *, team: Team, user: Any) -> None:
    """Check the warehouse tables a metric uses before it is saved: access first, then column types.

    Raise PermissionDenied if a metric uses an ExperimentDataWarehouseNode whose warehouse table
    or view the user can't access. Background recomputes bypass warehouse access control (they
    run without a request user), so access must be enforced when the metric is created or
    updated — otherwise an inaccessible table would be saved and only fail later, during
    recalculation. The access decision is delegated to the HogQL database build (the same code
    that enforces warehouse access at query time) rather than re-derived here.

    Raise ValidationError if a metric's timestamp_field is not a date or datetime column, so the
    metric does not save and then fail on every recalculation.
    """
    table_names = collect_metric_warehouse_tables(metrics)
    if not table_names:
        # No warehouse nodes in the metric — skip the database build.
        return

    # Synthetic principals (project secret API keys) and anonymous/userless callers bypass warehouse
    # access control at query time, so there's nothing to enforce against for them.
    is_user = isinstance(user, User)
    database = Database.create_for(
        team=team, user=user if is_user else None, bypass_warehouse_access_control=not is_user
    )
    if is_user:
        blocked = sorted(name for name in table_names if database.is_table_access_denied(name))
        if blocked:
            raise PermissionDenied("You don't have access to data warehouse table(s): " + ", ".join(blocked))

    enforce_warehouse_metric_timestamp_types(metrics, database)
