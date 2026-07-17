from typing import Any

from rest_framework.exceptions import PermissionDenied

from posthog.hogql.database.database import Database

from posthog.models.team.team import Team
from posthog.models.user import User

from products.experiments.backend.metric_utils import collect_metric_warehouse_tables


def enforce_warehouse_metric_access(metrics: list[dict[str, Any]], *, team: Team, user: Any) -> None:
    """Raise PermissionDenied if a metric uses an ExperimentDataWarehouseNode whose warehouse table
    or view the user can't access.

    Background recomputes bypass warehouse access control (they run without a request user), so access
    must be enforced when the metric is created or updated — otherwise an inaccessible table would be
    saved and only fail later, during recalculation.

    The access decision is delegated to the HogQL database build (the same code that enforces
    warehouse access at query time) rather than re-derived here.
    """
    # Synthetic principals (project secret API keys) and anonymous/userless callers bypass warehouse
    # access control at query time, so there's nothing to enforce against here.
    if not isinstance(user, User):
        return

    table_names = collect_metric_warehouse_tables(metrics)
    if not table_names:
        # No warehouse nodes in the metric — skip the database build.
        return

    database = Database.create_for(team=team, user=user)
    blocked = sorted(name for name in table_names if database.is_table_access_denied(name))
    if blocked:
        raise PermissionDenied("You don't have access to data warehouse table(s): " + ", ".join(blocked))
