"""Terminal output and confirmation helpers shared by the support CLI scripts."""

import os
import sys
from collections import Counter
from typing import Optional, TextIO

from .errors import PostHogScriptError

_log_file: Optional[TextIO] = None


def resolve_output_base(base: str) -> str:
    """Return `base`, or `base-2`/`base-3`/... if its findings/log files already exist.

    Keeps a --output run from clobbering a previous one's report or transcript. Both files
    always share the same resolved base, so e.g. `NAME-2-findings.json` pairs with
    `NAME-2-log.txt`.
    """
    candidate = base
    suffix = 1
    while os.path.exists(f"{candidate}-findings.json") or os.path.exists(f"{candidate}-log.txt"):
        suffix += 1
        candidate = f"{base}-{suffix}"
    if candidate != base:
        log(f"  {base}-findings.json / {base}-log.txt already exist - using {candidate} instead")
    return candidate


def set_log_file(path: str) -> None:
    """Stream every subsequent log() call to `path` too, starting fresh.

    Opens `path` once, in write mode, so every log() line lands in it as it happens, in the
    same order the operator sees on stderr - a crash or Ctrl-C mid-run still leaves a
    complete transcript up to that point, rather than losing output that was only ever held
    in memory.
    """
    global _log_file
    _log_file = open(path, "w")


def close_log_file() -> None:
    """Flush and close the file opened by set_log_file(), if any. Safe to call unconditionally."""
    global _log_file
    if _log_file is not None:
        _log_file.close()
        _log_file = None


def log(message: str) -> None:
    """Write a progress/report line to stderr, keeping stdout free for piped data."""
    print(message, file=sys.stderr)  # noqa: T201 - stderr logging is this CLI's output channel
    if _log_file is not None:
        _log_file.write(message + "\n")
        _log_file.flush()


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
