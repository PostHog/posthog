from collections.abc import Iterator
from contextlib import contextmanager

from posthog.models import Team

from products.tasks.backend.exceptions import ComputeBillingLimitError, OrganizationExecutionError


def check_organization_execution(team_id: int) -> None:
    state = (
        Team.objects.filter(id=team_id)
        .values_list("organization__is_pending_deletion", "organization__is_active")
        .first()
    )
    if state is None:
        raise OrganizationExecutionError(
            "This organization no longer exists. Select another organization to run tasks.",
            team_id,
            "organization_not_found",
        )
    pending_deletion, active = state
    if pending_deletion:
        raise OrganizationExecutionError(
            "This organization is scheduled for deletion. Select another organization to run tasks.",
            team_id,
            "organization_pending_deletion",
        )
    if not active:
        raise ComputeBillingLimitError({"team_id": team_id}, "organization_deactivated")


@contextmanager
def guard_organization_execution(team_id: int) -> Iterator[None]:
    check_organization_execution(team_id)
    try:
        yield
    except Exception:
        check_organization_execution(team_id)
        raise
