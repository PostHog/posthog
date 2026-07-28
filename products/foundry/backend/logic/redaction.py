"""Value-based secret redaction for anything a managed node's sandbox reports back.

``products/tasks``' ``redact_sandbox_command`` redacts by *name* (a fixed set of known
env var names via regex) — useful for the one log line that runs the raw command, but
useless against a foundry-event note/knowledge/artifact payload that merely *contains* a
secret value with no accompanying variable name (e.g. an agent echoing a token into a
free-text message). This module redacts by *value* instead: given the actual secret
strings from a node's ``run_config.env`` allowlist, scrub any occurrence of them out of
whatever the node reported before it becomes a BetEvent — the one place ADR-5 requires a
secret can never round-trip through, regardless of how it ended up on stdout.
"""

from __future__ import annotations

import re
from typing import Any

FOUNDRY_REDACTED_PLACEHOLDER = "<redacted>"

# Matched against env var *names*, not values — deliberately narrower than "every long env
# value": a build-loop node's env also carries FOUNDRY_TARGET_REPO_URL/memory_repo_url-style
# fields, which legitimately need to round-trip into a structured `artifact.ready.repo_url`
# (same convention as the Bet's own `memory_repo_url`, stored and exposed since iteration 2).
# A bare API key/token/secret has no legitimate reason to appear in any BetEvent, structured
# or not, so those are the only values this treats as unconditionally forbidden.
_CREDENTIAL_ENV_NAME_PATTERN = re.compile(r"(API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)


def secret_values_from_env(env: dict[str, str] | None) -> list[str]:
    """Values worth redacting out of a node's env allowlist: ones whose *name* marks them
    as a bare credential (API key, token, secret, password) rather than operational
    metadata like a repo URL."""
    if not env:
        return []
    return [v for k, v in env.items() if v and _CREDENTIAL_ENV_NAME_PATTERN.search(k)]


def redact_secret_values(value: Any, secrets: list[str]) -> Any:
    """Recursively scrub every occurrence of any ``secrets`` value out of ``value``.

    Handles the shapes a parsed foundry-event payload actually takes (str / dict / list);
    anything else (numbers, bools, None) is returned unchanged.
    """
    if not secrets:
        return value
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, FOUNDRY_REDACTED_PLACEHOLDER)
        return redacted
    if isinstance(value, dict):
        return {k: redact_secret_values(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secret_values(v, secrets) for v in value]
    return value
