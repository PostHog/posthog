from dataclasses import dataclass

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
    # Keep the activity and its wire contract for existing workflow histories. Limits now
    # apply at pipeline admission; an accepted pipeline can finish even after the cap is hit.
    return SELF_DRIVING_QUOTA_STOP_CHECKING
