from typing import Never

from rest_framework.exceptions import APIException, NotFound, Throttled, ValidationError

from posthog.exceptions import Conflict

from products.wizard.backend.facade.errors import (
    ActiveWizardRunError,
    InvalidBranchError,
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
from products.wizard.backend.presentation.runs.errors import WIZARD_RUN_CREATION_ERRORS, WizardRunCreationError

WizardInstallStartError = WizardRunCreationError | InvalidBranchError

WIZARD_INSTALL_START_ERRORS = (*WIZARD_RUN_CREATION_ERRORS, InvalidBranchError)


def install_start_api_error(error: WizardInstallStartError) -> APIException:
    match error:
        case InvalidRepositoryError():
            return ValidationError("Enter a repository in owner/name format.", code="invalid_repository")
        case InvalidBranchError():
            return ValidationError("Enter a valid branch name, such as main.", code="invalid_branch")
        case MissingGitHubIntegrationError():
            return ValidationError(
                "This project isn't connected to GitHub. Connect GitHub to the project, then try again.",
                code="github_not_connected",
            )
        case RepositoryNotAccessibleError():
            return ValidationError(
                "PostHog can't access this repository. Add it to the repositories the PostHog GitHub App can "
                "access, then try again.",
                code="repository_not_accessible",
            )
        case ActiveWizardRunError():
            return Conflict(
                "You already have a setup run in progress for this project. Wait for it to finish, then try again.",
                code="run_already_active",
            )
        case WizardRunIdempotencyConflictError():
            return Conflict(
                "This idempotency key was already used for a different setup run. Use a new key.",
                code="idempotency_conflict",
            )
        case WizardRunHourlyLimitError():
            return Throttled(detail="You've reached the hourly limit for setup runs. Try again in an hour.")
        case WizardRunDailyLimitError():
            return Throttled(detail="You've reached the daily limit for setup runs. Try again tomorrow.")
        case (
            WizardProgramNotAvailableError()
            | WizardProgramEnvironmentNotSupportedError()
            | InvalidWorkspaceEnvironmentError()
        ):
            return NotFound("Cloud setup runs aren't available for this project.")

    _unexpected_install_start_error(error)


def _unexpected_install_start_error(error: Never) -> Never:
    raise AssertionError(f"Unexpected Wizard install start error: {error!r}")
