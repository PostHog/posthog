from itertools import product

import pytest

from products.wizard.backend.facade.enums import WizardRunErrorCode, WizardRunStatus
from products.wizard.backend.facade.errors import IllegalStatusTransitionError, InvalidTransitionMetadataError
from products.wizard.backend.logic.runs import validation
from products.wizard.backend.logic.runs.transitions import transition

ALLOWED_TRANSITIONS = (
    (WizardRunStatus.CREATED, WizardRunStatus.RUNNING),
    (WizardRunStatus.CREATED, WizardRunStatus.FAILED),
    (WizardRunStatus.CREATED, WizardRunStatus.CANCELLED),
    (WizardRunStatus.RUNNING, WizardRunStatus.COMPLETED),
    (WizardRunStatus.RUNNING, WizardRunStatus.FAILED),
    (WizardRunStatus.RUNNING, WizardRunStatus.CANCELLED),
)

ILLEGAL_TRANSITIONS = tuple(
    transition for transition in product(WizardRunStatus, repeat=2) if transition not in ALLOWED_TRANSITIONS
)


@pytest.mark.parametrize("current_status, next_status", ALLOWED_TRANSITIONS)
def test_run_accepts_valid_status_transitions(current_status: WizardRunStatus, next_status: WizardRunStatus) -> None:
    error_code = WizardRunErrorCode.TIMEOUT if next_status == WizardRunStatus.FAILED else None

    assert transition(current_status, next_status, error_code=error_code) == next_status


@pytest.mark.parametrize("current_status, next_status", ILLEGAL_TRANSITIONS)
def test_run_rejects_invalid_status_transitions(current_status: WizardRunStatus, next_status: WizardRunStatus) -> None:
    with pytest.raises(IllegalStatusTransitionError):
        transition(current_status, next_status)


def test_run_rejects_error_code_for_non_failed_status() -> None:
    with pytest.raises(InvalidTransitionMetadataError):
        transition(
            WizardRunStatus.RUNNING,
            WizardRunStatus.COMPLETED,
            error_code=WizardRunErrorCode.TIMEOUT,
        )


def test_failed_transition_allows_missing_error_code() -> None:
    assert transition(WizardRunStatus.RUNNING, WizardRunStatus.FAILED) == WizardRunStatus.FAILED


def test_status_transition_invariants_are_not_validation_rules() -> None:
    assert not hasattr(validation, "validate_status_transition")
