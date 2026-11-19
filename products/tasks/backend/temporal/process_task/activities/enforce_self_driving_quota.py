from dataclasses import dataclass
from uuid import UUID

from temporalio import activity

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
    # pipeline admission, so accepted work finishes. Refresh trial compute costs while it runs
    # so new admissions see the allowance being consumed, including absorbed spillover.
    from products.signals.backend.facade.trial import (
        refresh_trial_run_spend,  # noqa: PLC0415 -- Signals imports Tasks facade
    )

    if refresh_trial_run_spend(team_id=input.team_id, run_id=UUID(input.run_id)):
        return SELF_DRIVING_QUOTA_PROCEED
    return SELF_DRIVING_QUOTA_STOP_CHECKING
