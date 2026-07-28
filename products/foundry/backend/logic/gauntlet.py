"""Pure, sandbox-agnostic gauntlet check logic: diff parsing, coverage/mutation report
parsing, and the protected_paths/flag_guard heuristics.

Kept free of Temporal/sandbox imports so every rule here is unit-testable without a
workflow environment; ``temporal/gate_activities.py`` is a thin shell that runs commands
in a sandbox, gathers their output, and calls straight into these functions.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

import defusedxml.ElementTree as ET


@dataclass(frozen=True)
class CheckOutcome:
    passed: bool
    detail: str


# ---- unified diff parsing (git diff output) ----

_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_files_from_diff(diff_text: str) -> list[str]:
    """File paths touched by a unified diff (the ``b/`` side), in first-seen order."""
    files: list[str] = []
    for line in diff_text.splitlines():
        match = _DIFF_FILE_RE.match(line)
        if match and match.group(1) != "/dev/null" and match.group(1) not in files:
            files.append(match.group(1))
    return files


def added_lines_by_file(diff_text: str) -> dict[str, set[int]]:
    """Post-image line numbers introduced or modified by a unified diff, per file.

    Walks each file's hunks tracking the running new-file line counter: a ``+`` line
    contributes its current line number and advances the counter, a context line only
    advances it, and a ``-`` line does neither. The old-file header (``--- a/...``) is
    never matched as a file boundary (only ``+++ b/...`` is), so it free-rides through
    as an inert ``-``-prefixed line between file boundaries.
    """
    result: dict[str, set[int]] = {}
    current_file: str | None = None
    current_line = 0
    for line in diff_text.splitlines():
        file_match = _DIFF_FILE_RE.match(line)
        if file_match:
            current_file = None if file_match.group(1) == "/dev/null" else file_match.group(1)
            continue
        hunk_match = _DIFF_HUNK_RE.match(line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue
        if current_file is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.setdefault(current_file, set()).add(current_line)
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            current_line += 1
    return result


def added_line_text_by_file(diff_text: str) -> dict[str, list[str]]:
    """Content of ``+`` lines per file — the flag_guard heuristic's textual counterpart
    to ``added_lines_by_file``'s line numbers."""
    result: dict[str, list[str]] = {}
    current_file: str | None = None
    for line in diff_text.splitlines():
        file_match = _DIFF_FILE_RE.match(line)
        if file_match:
            current_file = None if file_match.group(1) == "/dev/null" else file_match.group(1)
            continue
        if current_file is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.setdefault(current_file, []).append(line[1:])
    return result


# ---- coverage report parsing ----


def parse_lcov(content: str) -> dict[str, dict[int, int]]:
    """``SF:``/``DA:``/``end_of_record`` sections into {file: {line: hit_count}}."""
    hits: dict[str, dict[int, int]] = {}
    current_file: str | None = None
    for line in content.splitlines():
        if line.startswith("SF:"):
            current_file = line[len("SF:") :].strip()
            hits.setdefault(current_file, {})
        elif line.startswith("DA:") and current_file is not None:
            parts = line[len("DA:") :].split(",")
            if len(parts) >= 2:
                hits[current_file][int(parts[0])] = int(parts[1])
        elif line.strip() == "end_of_record":
            current_file = None
    return hits


def parse_cobertura(content: str) -> dict[str, dict[int, int]]:
    """Cobertura-format XML (coverage.py's ``coverage xml`` output) into {file: {line: hit_count}}."""
    hits: dict[str, dict[int, int]] = {}
    root = ET.fromstring(content)
    for class_el in root.iter("class"):
        filename = class_el.get("filename")
        if not filename:
            continue
        file_hits = hits.setdefault(filename, {})
        lines_el = class_el.find("lines")
        if lines_el is None:
            continue
        for line_el in lines_el.findall("line"):
            number, hit_count = line_el.get("number"), line_el.get("hits")
            if number is not None and hit_count is not None:
                file_hits[int(number)] = int(hit_count)
    return hits


_COVERAGE_PARSERS = {"lcov": parse_lcov, "cobertura": parse_cobertura}


def compute_changed_line_coverage(
    added_lines: dict[str, set[int]], hits: dict[str, dict[int, int]]
) -> tuple[float, int, int]:
    """Percentage of the diff's added/changed lines that are covered.

    Matches a diff file path to a report file path exactly first, falling back to a
    basename match (coverage tools sometimes emit paths relative to a different root
    than git does). Files with no added lines contribute nothing to the total.
    """
    total = 0
    covered = 0
    for file, lines in added_lines.items():
        file_hits = hits.get(file)
        if file_hits is None:
            basename = file.rsplit("/", 1)[-1]
            file_hits = next((h for path, h in hits.items() if path == basename or path.endswith("/" + basename)), None)
        for line_no in lines:
            total += 1
            if file_hits is not None and file_hits.get(line_no, 0) > 0:
                covered += 1
    pct = (covered / total * 100) if total else 100.0
    return pct, covered, total


def coverage_check_outcome(
    *, diff_text: str, report_content: str, report_format: str, min_changed_line_pct: float
) -> CheckOutcome:
    parser = _COVERAGE_PARSERS.get(report_format)
    if parser is None:
        return CheckOutcome(passed=False, detail=f"unknown coverage report_format '{report_format}'")
    hits = parser(report_content)
    pct, covered, total = compute_changed_line_coverage(added_lines_by_file(diff_text), hits)
    detail = (
        f"{covered}/{total} changed lines covered ({pct:.1f}%, min {min_changed_line_pct:.1f}%)"
        if total
        else "no added/changed lines to cover"
    )
    return CheckOutcome(passed=pct >= min_changed_line_pct, detail=detail)


# ---- mutation command resolution + report parsing (mutmut's ``mutmut junitxml`` output) ----

MUTATION_REPORT_PATH = "mutmut-report.xml"
_DEFAULT_MUTATION_COMMAND_TEMPLATE = (
    "mutmut run --paths-to-mutate {files} --no-progress; mutmut junitxml > " + MUTATION_REPORT_PATH
)


def resolve_mutation_command(command_template: str, changed_files: list[str]) -> str:
    """Fill '{files}' in a mutation command template with the shell-quoted changed files.

    A configured template is trusted as-is (it may target any language/tool); the built-in
    fallback is mutmut-specific, so it additionally restricts itself to changed ``.py`` files
    (mutmut has nothing to mutate in anything else). Falls back to mutating the whole tree
    (``.``) only if the diff touched no files of the relevant kind — better an over-broad
    mutation run than a `mutmut` invocation with an empty --paths-to-mutate.
    """
    if command_template:
        files_arg = shlex.join(changed_files) if changed_files else "."
        return command_template.format(files=files_arg)
    python_files = [f for f in changed_files if f.endswith(".py")]
    files_arg = shlex.join(python_files) if python_files else "."
    return _DEFAULT_MUTATION_COMMAND_TEMPLATE.format(files=files_arg)


# ---- mutation report parsing (mutmut's ``mutmut junitxml`` output) ----


def parse_mutation_junitxml(content: str) -> tuple[float, int, int]:
    """A testcase with no failure/error child is a killed mutant; one with a failure or
    error child survived (or errored/timed out). Score is killed / total."""
    root = ET.fromstring(content)
    testcases = list(root.iter("testcase"))
    total = len(testcases)
    killed = sum(1 for tc in testcases if tc.find("failure") is None and tc.find("error") is None)
    pct = (killed / total * 100) if total else 0.0
    return pct, killed, total


def mutation_check_outcome(*, report_content: str, min_score_pct: float) -> CheckOutcome:
    pct, killed, total = parse_mutation_junitxml(report_content)
    if total == 0:
        return CheckOutcome(passed=False, detail="no mutants were generated for the changed files")
    detail = f"{killed}/{total} mutants killed ({pct:.1f}%, min {min_score_pct:.1f}%)"
    return CheckOutcome(passed=pct >= min_score_pct, detail=detail)


# ---- protected_paths (the Uncle-Bob invariant) ----


def protected_paths_check_outcome(changed_files: list[str], protected_paths: list[str]) -> CheckOutcome:
    touched = sorted({f for f in changed_files for p in protected_paths if f.startswith(p)})
    if touched:
        return CheckOutcome(passed=False, detail=f"artifact diff touches protected path(s): {', '.join(touched)}")
    return CheckOutcome(passed=True, detail="no protected paths touched")


# ---- flag_guard (heuristic, not sound — see docstring) ----


def flag_guard_check_outcome(
    *, diff_text: str, changed_files: list[str], flag_key: str, exempt_paths: list[str]
) -> CheckOutcome:
    """Grep-level heuristic: does every changed, non-exempt file's diff contain a
    reference to ``flag_key`` somewhere in its added lines?

    Known limitations, stated rather than fixed: this is textual, not semantic. A
    ``flag_key`` substring anywhere in a changed file's added lines (a comment, a log
    message, an unrelated identifier) passes it; a change correctly gated indirectly
    (behind a shared helper that checks the flag elsewhere) is flagged as unguarded. It's
    a fast tripwire meant to catch an obviously-unguarded change, not proof of correct
    gating — treat a failure as a prompt to look, not a verdict.
    """
    if not flag_key:
        return CheckOutcome(passed=True, detail="no flag_key configured, skipping")
    added_by_file = added_line_text_by_file(diff_text)
    unguarded = sorted(
        f
        for f in changed_files
        if not any(f.startswith(p) for p in exempt_paths) and flag_key not in "\n".join(added_by_file.get(f, []))
    )
    if unguarded:
        return CheckOutcome(
            passed=False, detail=f"changed file(s) with no reference to flag '{flag_key}': {', '.join(unguarded)}"
        )
    return CheckOutcome(passed=True, detail=f"every changed, non-exempt file references '{flag_key}'")
