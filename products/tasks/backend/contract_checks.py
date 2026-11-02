import structlog

from products.tasks.backend.facade.profiles import ContractCheck, TaskProfile
from products.tasks.backend.metrics import observe_contract_violation

logger = structlog.get_logger(__name__)


def contract_violation_refused(profile: TaskProfile, check: ContractCheck, detail: str) -> bool:
    refused = check in profile.enforced_checks
    observe_contract_violation(check=check.value, profile=profile.key)
    logger.warning(
        "task_contract_violation_refused" if refused else "task_contract_violation_would_refuse",
        check=check.value,
        profile=profile.key,
        detail=detail,
    )
    return refused
