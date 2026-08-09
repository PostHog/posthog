"""Terminal output and confirmation helpers shared by the support CLI scripts."""

import sys
from collections import Counter

from .errors import PostHogScriptError


def log(message: str) -> None:
    """Write a progress/report line to stderr, keeping stdout free for piped data."""
    print(message, file=sys.stderr)  # noqa: T201 - stderr logging is this CLI's output channel


def printable(value: str) -> str:
    """Escape terminal control sequences in untrusted text (e.g. ingested property or person names).

    Ingested data can carry ANSI/control sequences that would otherwise spoof or wipe the
    operator's terminal when a name or an API error is previewed or reported.
    """
    return "".join(ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii") for ch in str(value))


def format_status_counts(counts: Counter[str]) -> str:
    """Render a status-code histogram like 'HTTP 204: 39, HTTP 403: 11' (digit codes first)."""
    parts = []
    for code in sorted(counts, key=lambda c: (not c.isdigit(), c)):
        label = f"HTTP {code}" if code.isdigit() else code
        parts.append(f"{label}: {counts[code]}")
    return ", ".join(parts)


def confirm(prompt: str, expected: str, *, eof_message: str) -> bool:
    """Read one line from stdin; return True iff it matches `expected` (trimmed, case-insensitive).

    A closed stdin (a piped or otherwise non-interactive run) raises PostHogScriptError with
    `eof_message` instead of a bare EOFError traceback, so the caller can point the operator at
    --yes or a personal API key.
    """
    try:
        reply = input(prompt)
    except EOFError as err:
        raise PostHogScriptError(eof_message) from err
    return reply.strip().lower() == expected.strip().lower()
