from products.wizard.backend.facade.contracts import WizardRunDTO
from products.wizard.backend.facade.enums import WizardRunErrorCode, WizardRunStage, WizardRunStatus

LOCAL_WIZARD_COMMAND = "npx -y @posthog/wizard@latest"

_CHECK_AGAIN = "Check the status again in about 30 seconds."
_START_AGAIN = "Start a new run when the user is ready."
_RUN_LOCALLY = f"Start a new run, or suggest running Wizard on their machine with `{LOCAL_WIZARD_COMMAND}`."


def next_step(run: WizardRunDTO, pull_request_url: str | None) -> str:
    """
    A sentence an agent can relay to the user about what happens next with a cloud setup run.
    """
    match run.status:
        case WizardRunStatus.CREATED:
            return f"The setup agent is queued. {_CHECK_AGAIN}"
        case WizardRunStatus.RUNNING:
            return f"{_running_stage(run.stage)} {_CHECK_AGAIN}"
        case WizardRunStatus.COMPLETED if pull_request_url is not None:
            return (
                "The setup agent opened a pull request. Share the link with the user so they can review and merge it."
            )
        case WizardRunStatus.COMPLETED:
            return (
                "The setup agent finished without changing any files. The repository may already have PostHog set up."
            )
        case WizardRunStatus.CANCELLED:
            return f"This run was canceled. {_START_AGAIN}"
        case _:
            return _failure(run.error_code)


def _running_stage(stage: WizardRunStage | None) -> str:
    match stage:
        case WizardRunStage.PREPARING_WORKSPACE:
            return "The setup agent is cloning the repository."
        case WizardRunStage.EXECUTING_WIZARD:
            return "The setup agent is adding PostHog to the code. This usually takes a few minutes."
        case WizardRunStage.CREATING_ARTIFACTS:
            return "The setup agent is opening a pull request."
        case _:
            return "The setup agent is starting a cloud workspace."


def _failure(error_code: str | None) -> str:
    match error_code:
        case WizardRunErrorCode.REPOSITORY_ACCESS_FAILED:
            return (
                "PostHog could not access the repository. Ask the user to give the PostHog GitHub App access to it, "
                "then start a new run."
            )
        case WizardRunErrorCode.WORKSPACE_PREPARATION_FAILED:
            return "The setup agent could not clone the repository. Check that the branch exists, then start a new run."
        case WizardRunErrorCode.PROVISIONING_FAILED | WizardRunErrorCode.DISPATCH_FAILED:
            return "PostHog could not start a cloud workspace. Wait a few minutes, then start a new run."
        case WizardRunErrorCode.ARTIFACT_CREATION_FAILED:
            return (
                "The setup agent made changes but could not open a pull request. Check that the PostHog GitHub App "
                "can write to the repository, then start a new run."
            )
        case WizardRunErrorCode.TIMEOUT:
            return f"The run took too long and stopped. {_RUN_LOCALLY}"
        case _:
            return f"The setup agent could not finish. {_RUN_LOCALLY}"
