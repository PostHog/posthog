from products.wizard.backend.facade.contracts import WizardSessionOwnershipError as WizardSessionOwnershipError


class MissingGitHubIntegrationError(Exception):
    pass


class RepositoryNotAccessibleError(Exception):
    pass


class InvalidWorkspaceEnvironmentError(Exception):
    pass


class InvalidRepositoryError(Exception):
    pass


class WizardProgramNotAvailableError(Exception):
    pass


class WizardProgramEnvironmentNotSupportedError(Exception):
    pass


class IllegalStatusTransitionError(Exception):
    pass


class InvalidTransitionMetadataError(Exception):
    pass


class WizardRunNotFoundError(Exception):
    pass


class WizardRunArtifactNotFoundError(Exception):
    pass


class WizardRunArtifactTooLargeError(Exception):
    pass


class WizardRunIdempotencyConflictError(Exception):
    pass


class MissingWizardRunIdempotencyKeyError(Exception):
    pass


class ActiveWizardRunError(Exception):
    pass


class WizardRunHourlyLimitError(Exception):
    pass


class WizardRunDailyLimitError(Exception):
    pass
