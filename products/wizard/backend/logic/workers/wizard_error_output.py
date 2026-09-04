import json

from products.wizard.backend.facade.validation import is_wizard_error_code
from products.wizard.backend.logic.workers.config import WIZARD_ERROR_OUTPUT_PREFIX


def wizard_error_code_from_stderr(stderr: str) -> str | None:
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

        return code

    return None
