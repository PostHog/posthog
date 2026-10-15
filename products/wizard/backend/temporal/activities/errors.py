from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from temporalio.exceptions import ApplicationError, CancelledError

WIZARD_REPOSITORY_ACCESS_ERROR_TYPE = "WizardRepositoryAccessError"
WIZARD_RUN_CONFIGURATION_ERROR_TYPE = "WizardRunConfigurationError"
WIZARD_WORKER_EXECUTION_ERROR_TYPE = "WizardWorkerExecutionError"
WIZARD_WORKER_TIMEOUT_ERROR_TYPE = "WizardWorkerTimeoutError"

P = ParamSpec("P")
T = TypeVar("T")


def sanitize_activity_errors(function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return function(*args, **kwargs)
        except CancelledError:
            raise
        except ApplicationError as error:
            safe_error = ApplicationError(
                "Wizard activity failed.",
                type=error.type,
                non_retryable=error.non_retryable,
                next_retry_delay=error.next_retry_delay,
                category=error.category,
            )
        except Exception as error:
            safe_error = ApplicationError("Wizard activity failed.", type=type(error).__name__)

        # Temporal exports exception messages and stacks. Raise outside the handler so neither
        # __cause__ nor __context__ carries sandbox output into traces or workflow history.
        raise safe_error from None

    return wrapped
