from products.wizard.backend.facade.enums import WizardRunErrorCode


def error_message(error_code: str | None) -> str | None:
    match error_code:
        case WizardRunErrorCode.TIMEOUT:
            return "The Wizard run timed out."
        case WizardRunErrorCode.PROVISIONING_FAILED:
            return "The Wizard Worker could not be provisioned."
        case WizardRunErrorCode.REPOSITORY_ACCESS_FAILED:
            return "The Wizard Worker could not access the repository."
        case WizardRunErrorCode.WORKSPACE_PREPARATION_FAILED:
            return "The Wizard Worker could not prepare the workspace."
        case WizardRunErrorCode.EXECUTION_FAILED:
            return "The Wizard could not complete the selected program."
        case WizardRunErrorCode.ARTIFACT_CREATION_FAILED:
            return "The Wizard Worker could not create run artifacts."
        case WizardRunErrorCode.DISPATCH_FAILED:
            return "The Wizard run could not be dispatched."
        case None:
            return None
        case value if value.startswith("PHW_"):
            return "The Wizard could not complete the selected program."
        case _:
            return "The Wizard run failed."
