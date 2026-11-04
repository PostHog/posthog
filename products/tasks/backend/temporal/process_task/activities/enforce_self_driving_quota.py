from dataclasses import dataclass
from uuid import UUID

from temporalio import activity

from posthog.models import Team
from posthog.temporal.common.utils import asyncify

SELF_DRIVING_QUOTA_PROCEED = "proceed"
SELF_DRIVING_QUOTA_STOP_CHECKING = "stop_checking"
SELF_DRIVING_QUOTA_CANCELLED = "cancelled"


@dataclass
class EnforceSelfDrivingRunQuotaInput:
    run_id: str
    task_id: str
    team_id: int


@activity.defn
@asyncify
def enforce_self_driving_run_quota(input: EnforceSelfDrivingRunQuotaInput) -> str:
    # Keep the activity and its wire contract for existing workflow histories. Limits apply at
    # pipeline admission, so an accepted pipeline can finish after the cap is hit. Trial-funded
    # runs are the exception: the one-time allowance is not billed, so overspend has no payer.
    from products.signals.backend.facade.trial import (
        check_trial_run_quota,  # noqa: PLC0415 -- trial cancellation imports this workflow package
    )

    trial_outcome = check_trial_run_quota(team=Team.objects.get(id=input.team_id), run_id=UUID(input.run_id))
    if trial_outcome is not None:
        return trial_outcome
    return SELF_DRIVING_QUOTA_STOP_CHECKING
