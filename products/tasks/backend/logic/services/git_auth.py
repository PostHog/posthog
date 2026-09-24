"""Recognize a git operation that failed because it had no usable GitHub credential."""

import re

# What git prints when it cannot authenticate. The HTTPS forms come from
# `GIT_TERMINAL_PROMPT=0` refusing to prompt for a username the sandbox has no
# way to supply; the ssh forms from a remote that fell through to SSH.
_GIT_AUTH_FAILURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"could not read (username|password)", re.IGNORECASE),
    re.compile(r"terminal prompts disabled", re.IGNORECASE),
    re.compile(r"authentication failed", re.IGNORECASE),
    re.compile(r"invalid username or (token|password)", re.IGNORECASE),
    re.compile(r"remote: repository not found", re.IGNORECASE),
    re.compile(r"the requested url returned error: 40[13]", re.IGNORECASE),
    re.compile(r"permission denied \(publickey", re.IGNORECASE),
    re.compile(r"host key verification failed", re.IGNORECASE),
    re.compile(r"please make sure you have the correct access rights", re.IGNORECASE),
)


def is_git_auth_failure(*outputs: str | None) -> bool:
    combined = "\n".join(output for output in outputs if output)
    if not combined:
        return False
    return any(pattern.search(combined) for pattern in _GIT_AUTH_FAILURE_PATTERNS)
