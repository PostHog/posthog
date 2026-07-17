from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO

from django.conf import settings

import modal

ANSI_ESCAPE_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
MAX_PROVISION_LOG_EXCERPT_LINES = 80


@dataclass
class SandboxProvisionDiagnostics:
    summary_lines: list[str]
    raw_excerpt: str | None


def should_capture_modal_provision_diagnostics() -> bool:
    return bool(settings.DEBUG)


def _sanitize_modal_output(output: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in output.replace("\r", "\n").splitlines():
        line = ANSI_ESCAPE_REGEX.sub("", raw_line).strip()
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def summarize_modal_output(output: str) -> SandboxProvisionDiagnostics:
    cleaned = _sanitize_modal_output(output)
    if not cleaned:
        return SandboxProvisionDiagnostics(summary_lines=[], raw_excerpt=None)

    all_lines = cleaned.splitlines()
    summary_lines: list[str] = []
    seen_lines: set[str] = set()
    for line in all_lines:
        if not (
            "Building image " in line
            or line.startswith("=> Step ")
            or line.startswith("Copied image in ")
            or " newly installed" in line
            or line.startswith("Need to get ")
            or line.startswith("After this operation, ")
            or line.startswith("Fetched ")
            or line.startswith("Writing manifest to image destination")
            or line.startswith("Unpacking OCI image")
        ):
            continue
        if line in seen_lines:
            continue
        summary_lines.append(line)
        seen_lines.add(line)

    excerpt_lines = all_lines[:MAX_PROVISION_LOG_EXCERPT_LINES]
    raw_excerpt = "\n".join(excerpt_lines)
    if len(all_lines) > MAX_PROVISION_LOG_EXCERPT_LINES:
        raw_excerpt += "\n... (truncated)"

    return SandboxProvisionDiagnostics(summary_lines=summary_lines, raw_excerpt=raw_excerpt)


@contextmanager
def capture_modal_output_if_debug() -> Iterator[StringIO | None]:
    if not should_capture_modal_provision_diagnostics():
        yield None
        return

    stream = StringIO()
    with redirect_stdout(stream), redirect_stderr(stream):
        with modal.enable_output():
            yield stream
