"""Shared helpers for the PostHog support CLI scripts (scrub/prune).

Re-exports the common error type, console helpers, and PostHog REST client so a script can
`from lib import ...` one hardened surface instead of each carrying its own copy. Scripts run
directly (`python products/support/scripts/<name>.py`), which puts this directory on sys.path,
so `lib` imports without any packaging.
"""

from .console import confirm, format_status_counts, log, printable
from .errors import PostHogScriptError
from .posthog_api import MAX_RETRIES, request_with_retries, resolve_host, setup_session_auth

__all__ = [
    "MAX_RETRIES",
    "PostHogScriptError",
    "confirm",
    "format_status_counts",
    "log",
    "printable",
    "request_with_retries",
    "resolve_host",
    "setup_session_auth",
]
