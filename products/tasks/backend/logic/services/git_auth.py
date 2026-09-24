"""Classify a git operation that failed before it could read the repository."""

import re
from typing import Literal

# Why git could not reach the repository.
#   credentials — no usable token reached git, so it asked for one it could never get.
#   access      — a token reached git, but the account behind it cannot see the repository.
# Neither can succeed on a retry, and both need the same human action, but only the first
# means the credential plumbing failed. A host-key mismatch is deliberately absent: the
# server's identity failed verification, which says nothing about the credential.
GitFailureKind = Literal["credentials", "access"]

_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"could not read (username|password)", re.IGNORECASE),
    re.compile(r"terminal prompts disabled", re.IGNORECASE),
    re.compile(r"authentication failed", re.IGNORECASE),
    re.compile(r"invalid username or (token|password)", re.IGNORECASE),
    re.compile(r"the requested url returned error: 401", re.IGNORECASE),
    re.compile(r"permission denied \(publickey", re.IGNORECASE),
    re.compile(r"please make sure you have the correct access rights", re.IGNORECASE),
)

# GitHub answers 404 for a repository the caller cannot see, so "not found" here does not
# tell us whether the repository is missing or merely invisible to this account.
_ACCESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"remote: repository not found", re.IGNORECASE),
    re.compile(r"the requested url returned error: 403", re.IGNORECASE),
)


def classify_git_failure(*outputs: str | None) -> GitFailureKind | None:
    combined = "\n".join(output for output in outputs if output)
    if not combined:
        return None
    if any(pattern.search(combined) for pattern in _CREDENTIAL_PATTERNS):
        return "credentials"
    if any(pattern.search(combined) for pattern in _ACCESS_PATTERNS):
        return "access"
    return None
