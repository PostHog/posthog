import json

from posthog.dataclasses import frozen

from products.wizard.backend.facade.validation import is_wizard_error_code
from products.wizard.backend.logic.workers.config import WIZARD_ERROR_MESSAGE_LENGTH, WIZARD_ERROR_OUTPUT_PREFIX


@frozen
class WizardErrorLine:
    code: str
    message: str | None


def stderr_to_wizard_error(stderr: str) -> WizardErrorLine | None:
    for line in reversed(stderr.splitlines()):
        value = line.strip()
        if not value.startswith(WIZARD_ERROR_OUTPUT_PREFIX):
            continue

        try:
            payload = json.loads(value.removeprefix(WIZARD_ERROR_OUTPUT_PREFIX).strip())
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(payload, dict):
            return None

        code = payload.get("code")
        if not isinstance(code, str) or not is_wizard_error_code(code):
            return None

        message = payload.get("message")
        return WizardErrorLine(
            code=code,
            message=message[:WIZARD_ERROR_MESSAGE_LENGTH] if isinstance(message, str) and message else None,
        )

    return None
