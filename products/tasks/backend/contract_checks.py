import structlog

from products.tasks.backend.facade.profiles import ContractCheck, DrivePolicy, TaskProfile, find_task_profile
from products.tasks.backend.metrics import observe_contract_violation

logger = structlog.get_logger(__name__)


def contract_violation_refused(
    profile: TaskProfile, check: ContractCheck, detail: str, *, enforced: frozenset[ContractCheck] = frozenset()
) -> bool:
    refused = check in profile.enforced_checks | enforced
    observe_contract_violation(check=check.value, profile=profile.key)
    logger.warning(
        "task_contract_violation_refused" if refused else "task_contract_violation_would_refuse",
        check=check.value,
        profile=profile.key,
        detail=detail,
    )
    return refused


def drive_allowed(profile_key: str | None, *, created_by_id: int | None, user_id: int | None) -> bool:
    if not profile_key:
        return True
    profile = find_task_profile(profile_key)
    if profile is None:
        observe_contract_violation(check=ContractCheck.DRIVE.value, profile=profile_key)
        logger.warning(
            "task_contract_violation_unregistered_profile",
            check=ContractCheck.DRIVE.value,
            profile=profile_key,
            detail=f"no registered profile can say whether user {user_id} may drive a task owned by {created_by_id}",
        )
        return True
    if profile.drive == DrivePolicy.AUDIENCE:
        return True
    if profile.drive == DrivePolicy.OWNER and created_by_id is not None and created_by_id == user_id:
        return True
    detail = f"drive={profile.drive.value} does not let user {user_id} drive a task owned by {created_by_id}"
    return not contract_violation_refused(profile, ContractCheck.DRIVE, detail)
