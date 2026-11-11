import re
import json

from posthog.dataclasses import frozen

from products.wizard.backend.facade.validation import is_wizard_error_code
from products.wizard.backend.logic.workers.config import WIZARD_ERROR_MESSAGE_LENGTH, WIZARD_ERROR_OUTPUT_PREFIX

_REDACTED = "[REDACTED]"

# The Wizard copies raw exception text into this message, and the worker does not know the tokens the
# sandbox holds (the gateway token is minted inside it), so credentials are redacted by shape.
_CREDENTIAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bph[a-z]_[A-Za-z0-9_-]{8,}"), _REDACTED),
    (re.compile(r"\b(?:gh[oprsu]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})"), _REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), _REDACTED),
    (re.compile(r"(?<=://)[^/\s@]+@"), f"{_REDACTED}@"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {_REDACTED}"),
    (
        re.compile(r"""(?i)((?:api[_-]?key|token|secret|password)["']?\s*[:=]\s*["']?)[^\s"',;&]+"""),
        rf"\1{_REDACTED}",
    ),
)


def _redact_credentials(text: str) -> str:
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


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
        if not isinstance(message, str) or not message:
            return WizardErrorLine(code=code, message=None)

        # A stderr line can hold 64KB, so redaction runs on a bounded window to keep its cost fixed. The
        # window is twice the kept length, so a credential that crosses the final cut is still redacted
        # whole before the cut drops its tail.
        window = message[: 2 * WIZARD_ERROR_MESSAGE_LENGTH]
        return WizardErrorLine(code=code, message=_redact_credentials(window)[:WIZARD_ERROR_MESSAGE_LENGTH])

    return None
