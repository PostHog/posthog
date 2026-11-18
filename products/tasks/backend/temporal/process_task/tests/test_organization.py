import pytest

from products.tasks.backend.exceptions import ComputeBillingLimitError, OrganizationExecutionError
from products.tasks.backend.temporal.process_task.organization import check_organization_execution


@pytest.mark.django_db
@pytest.mark.parametrize(
    "pending_deletion, active, reason",
    [
        (False, True, None),
        (True, True, "organization_pending_deletion"),
        (True, False, "organization_pending_deletion"),
        (False, False, "organization_deactivated"),
    ],
)
def test_organization_execution_uses_current_state(team, pending_deletion, active, reason) -> None:
    check_organization_execution(team.id)
    organization = team.organization
    organization.is_pending_deletion = pending_deletion
    organization.is_active = active
    organization.save(update_fields=["is_pending_deletion", "is_active"])

    if reason is None:
        check_organization_execution(team.id)
    else:
        error_type = ComputeBillingLimitError if reason == "organization_deactivated" else OrganizationExecutionError
        with pytest.raises(error_type) as error:
            check_organization_execution(team.id)
        assert error.value.context["reason"] == reason
        assert error.value.non_retryable is True
