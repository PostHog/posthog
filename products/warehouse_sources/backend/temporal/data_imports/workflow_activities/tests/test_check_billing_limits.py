import uuid

import pytest

from posthog.models import Organization, Team

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits import (
    CheckBillingLimitsActivityInputs,
    check_billing_limits_activity,
)


def _team() -> Team:
    return Team.objects.create(organization=Organization.objects.create(name="org"), name="t")


# transaction=True: the activity calls close_old_connections(), which breaks the atomic wrapper
# a plain django_db test relies on for rollback (same reason test_calculate_table_size.py's
# activity-level test uses it).
@pytest.mark.django_db(transaction=True)
class TestCheckBillingLimitsActivity:
    def test_skips_check_when_job_does_not_exist(self) -> None:
        # job_id can arrive as None (or point at a job that's gone) from a legacy
        # create_external_data_job_model_activity result — this used to raise
        # ExternalDataJob.DoesNotExist and crash the whole workflow instead of skipping the check.
        team = _team()

        result = check_billing_limits_activity(
            CheckBillingLimitsActivityInputs(team_id=team.id, job_id=str(uuid.uuid4()))
        )

        assert result is False
