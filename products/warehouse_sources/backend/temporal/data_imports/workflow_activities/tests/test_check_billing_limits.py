import uuid

import pytest
from unittest.mock import patch

import redis.exceptions

from posthog.models import Organization, Team

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits import (
    CheckBillingLimitsActivityInputs,
    _team_is_rows_synced_limited,
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


class TestTeamIsRowsSyncedLimitedRetry:
    @patch("tenacity.nap.time.sleep")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits.is_team_limited"
    )
    def test_recovers_from_a_multi_attempt_redis_connect_blip(self, mock_is_team_limited, _mock_sleep) -> None:
        # The job-creation activity gives this check a single Temporal attempt, so a Redis blip
        # that outlasts the retry budget here fails the whole sync run instead of just this check.
        # A real ~18s blip exhausted the old 3-attempt budget; this guards that 4 timeouts in a row
        # still resolve instead of raising.
        mock_is_team_limited.side_effect = [
            redis.exceptions.TimeoutError("Timeout connecting to server"),
            redis.exceptions.TimeoutError("Timeout connecting to server"),
            redis.exceptions.TimeoutError("Timeout connecting to server"),
            redis.exceptions.TimeoutError("Timeout connecting to server"),
            False,
        ]

        assert _team_is_rows_synced_limited("token") is False
        assert mock_is_team_limited.call_count == 5

    @patch("tenacity.nap.time.sleep")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits.is_team_limited"
    )
    def test_reraises_after_the_retry_budget_is_exhausted(self, mock_is_team_limited, _mock_sleep) -> None:
        mock_is_team_limited.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")

        with pytest.raises(redis.exceptions.TimeoutError):
            _team_is_rows_synced_limited("token")

        assert mock_is_team_limited.call_count == 5
