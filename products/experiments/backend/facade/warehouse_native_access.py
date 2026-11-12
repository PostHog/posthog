"""The connection access check that the query status endpoint runs for a warehouse-native experiment result."""

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models.team import Team
from posthog.models.user import User

from products.experiments.backend.warehouse_native_sources import validate_warehouse_native_connection

# Stable wire identifier on an async query status. Renaming it needs a dual-read rollout and a drain of
# in-flight statuses, as for the managed warehouse labels.
WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX = "experiments-warehouse-native:"

__all__ = [
    "WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX",
    "validate_warehouse_native_connection_access",
]


def validate_warehouse_native_connection_access(team: Team, user: User | None, connection_id: str) -> None:
    """Raises PermissionDenied unless the user can read every table on the connection the result came from."""
    try:
        validate_warehouse_native_connection(connection_id, team=team, user=user)
    except ValidationError as error:
        # A connection the user cannot see and a deleted connection both come back as an invalid connection.
        # Either way the totals are not theirs to read.
        detail = error.detail[0] if isinstance(error.detail, list) else error.detail
        raise PermissionDenied(str(detail)) from error
