from products.wizard.backend.facade.enums import WizardRunStatus
from products.wizard.backend.facade.errors import IllegalStatusTransitionError, InvalidTransitionMetadataError

_ALLOWED_STATUS_TRANSITIONS = frozenset(
    {
        (WizardRunStatus.CREATED, WizardRunStatus.RUNNING),
        (WizardRunStatus.CREATED, WizardRunStatus.FAILED),
        (WizardRunStatus.CREATED, WizardRunStatus.CANCELLED),
        (WizardRunStatus.RUNNING, WizardRunStatus.COMPLETED),
        (WizardRunStatus.RUNNING, WizardRunStatus.FAILED),
        (WizardRunStatus.RUNNING, WizardRunStatus.CANCELLED),
    }
)


def transition(
    current_status: WizardRunStatus,
    next_status: WizardRunStatus,
    *,
    error_code: str | None = None,
) -> WizardRunStatus:
    if (current_status, next_status) not in _ALLOWED_STATUS_TRANSITIONS:
        raise IllegalStatusTransitionError
    if error_code is not None and next_status != WizardRunStatus.FAILED:
        raise InvalidTransitionMetadataError
    return next_status
