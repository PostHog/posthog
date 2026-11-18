from typing import Never

from rest_framework.exceptions import APIException, Throttled, ValidationError

from posthog.exceptions import Conflict

from products.wizard.backend.facade.errors import (
    ActiveWizardRunError,
    InvalidRepositoryError,
    InvalidWorkspaceEnvironmentError,
    MissingGitHubIntegrationError,
    RepositoryNotAccessibleError,
    WizardProgramEnvironmentNotSupportedError,
    WizardProgramNotAvailableError,
    WizardRunDailyLimitError,
    WizardRunHourlyLimitError,
    WizardRunIdempotencyConflictError,
)

WizardRunCreationError = (
    ActiveWizardRunError
    | InvalidRepositoryError
    | InvalidWorkspaceEnvironmentError
    | MissingGitHubIntegrationError
    | RepositoryNotAccessibleError
    | WizardProgramEnvironmentNotSupportedError
    | WizardProgramNotAvailableError
    | WizardRunDailyLimitError
    | WizardRunHourlyLimitError
    | WizardRunIdempotencyConflictError
)

WIZARD_RUN_CREATION_ERRORS = (
    ActiveWizardRunError,
    InvalidRepositoryError,
    InvalidWorkspaceEnvironmentError,
    MissingGitHubIntegrationError,
    RepositoryNotAccessibleError,
    WizardProgramEnvironmentNotSupportedError,
    WizardProgramNotAvailableError,
    WizardRunDailyLimitError,
    WizardRunHourlyLimitError,
    WizardRunIdempotencyConflictError,
)


def run_creation_api_error(error: WizardRunCreationError) -> APIException:
    match error:
        case InvalidWorkspaceEnvironmentError():
            return ValidationError({"detail": "Choose a workspace supported by this run environment."})
        case InvalidRepositoryError():
            return ValidationError({"detail": "Enter a repository in owner/name format."})
        case WizardProgramNotAvailableError():
            return ValidationError({"detail": "Choose an available Wizard program."})
        case WizardProgramEnvironmentNotSupportedError():
            return ValidationError({"detail": "Choose a Wizard program supported by this run environment."})
        case WizardRunIdempotencyConflictError():
            return Conflict(
                "This idempotency key was already used for a different Wizard run.",
                code="idempotency_conflict",
            )
        case ActiveWizardRunError():
            return Throttled(
                detail="A cloud Wizard run is already active. Wait for it to finish or cancel it before starting another."
            )
        case WizardRunHourlyLimitError():
            return Throttled(detail="You've reached the hourly cloud run limit. Try again in an hour.")
        case WizardRunDailyLimitError():
            return Throttled(detail="You've reached the daily cloud run limit. Try again tomorrow.")
        case MissingGitHubIntegrationError() | RepositoryNotAccessibleError():
            return ValidationError({"detail": "Connect GitHub with access to this repository, then try again."})

    _unexpected_run_creation_error(error)


def _unexpected_run_creation_error(error: Never) -> Never:
    raise AssertionError(f"Unexpected Wizard run creation error: {error!r}")
