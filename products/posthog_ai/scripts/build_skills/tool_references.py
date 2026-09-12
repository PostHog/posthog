# ruff: noqa: T201 allow print statements
"""Advisory lint for stale MCP tool and skill references in skill markdown."""

from __future__ import annotations

import os
import re
import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from . import source_files

# Tool/skill reference linting: skills must only reference MCP tools and skills that exist.
# The valid tool names come from the checked-in MCP schema registries (kept in sync with the
# sources by the schema drift check in ci-mcp.yml). Mirrors lint-tool-names.ts in services/mcp.
_MCP_SCHEMA_FILES = (
    "services/mcp/schema/tool-definitions.json",
    "services/mcp/schema/generated-tool-definitions.json",
)

# The reference check is heuristic and advisory: a candidate is only treated as a (stale) reference
# when it *resembles* a real name — within this many edits of a real tool/skill, or an exact
# casing miss. Real renames/typos sit at distance 1-2 from the intended name; ordinary hyphenated
# prose ("highest-error", "per-file") is far from every name. Backticks are not treated as intent
# (prose uses them for emphasis and field names too), so prose that does not resemble a real name is
# simply ignored — no name-level allowlist is needed for it. Findings are reported, never blocking.
_NEAR_MISS_MAX_EDITS = 2

# SDK / HogQL function names that legitimately appear as code in skills (e.g. `emit_signal(...)`,
# `get_feature_flag(...)`). They are real identifiers, not stale references, but collide with a
# tool-name suffix/near-miss, so they are held out of the reference check.
_SDK_FUNCTION_NAMES = {
    "feature_enabled",
    "get_feature_flag",
    "get_feature_flag_payload",
    "get_feature_flag_result",
    "get_all_flags",
    "get_all_flags_and_payloads",
    "apply_path_cleaning",
    "emit_signal",
}

# "use the X tool", "load the `X` skill" — kebab or snake candidate followed by tool/skill.
_PHRASE_REFERENCE_RE = re.compile(r"(?<![A-Za-z0-9_`-])`?([a-z0-9]+(?:[_-][a-z0-9]+)+)`?\s+(tools?|skills?)\b")

# "via `X`", "use `X`" — kebab-only (snake here is usually a field/SDK name, not a tool).
_INVOCATION_REFERENCE_RE = re.compile(
    r"\b(?:via|use|using|call|calling)\s+(?:the\s+)?`([a-z0-9]+(?:-[a-z0-9]+)+)`(?!\s*(?:tools?|skills?)\b)"
)

# A noun right after the backticked name means it's not a tool reference ("via the `x` feature flag").
_ENTITY_NOUN_RE = re.compile(r"\s+(?:feature|flag|event|property|properties|column|field|table|key|filter)s?\b")

# Backticked call syntax, e.g. `read_data("experiments", id)` — tool invocations written as calls.
# Deliberately skills-only (no equivalent in tool-references.ts): call-style references occur only
# in skill prose. The near-miss gate keeps SDK/HogQL examples (e.g. `get_feature_flag(...)`) quiet,
# since those names do not resemble any MCP tool.
_CALL_REFERENCE_RE = re.compile(r"`([a-z0-9]+(?:[_-][a-z0-9]+)+)\(")

# Backticked snake_case whose kebab form is a real tool — wrong casing.
_SNAKE_CASE_REFERENCE_RE = re.compile(r"`([a-z0-9]+(?:_[a-z0-9]+)+)`")


def _load_mcp_tool_names(repo_root: Path) -> set[str] | None:
    """Load valid MCP tool names from the checked-in schema registries.

    Returns None if no registry is available so the reference check can be skipped
    (keeps the lint runnable in checkouts without the MCP service).
    """
    names: set[str] = set()
    found = False
    for rel_path in _MCP_SCHEMA_FILES:
        schema_file = repo_root / rel_path
        if not schema_file.is_file():
            continue
        found = True
        names.update(json.loads(schema_file.read_text()).keys())
    return names if found else None


# The kinds produced by the phrase regex alternation `(tools?|skills?)`.
ReferenceKind = Literal["tool", "tools", "skill", "skills"]


@dataclass(frozen=True)
class ReferenceFinding:
    source_label: str
    line: int
    col: int
    name: str
    message: str


def _is_valid_reference(name: str, kind: ReferenceKind, tool_names: set[str], skill_names: set[str]) -> bool:
    if name in _SDK_FUNCTION_NAMES:
        return True
    registry = skill_names if kind in ("skill", "skills") else tool_names
    if name in registry:
        return True
    # Shorthand suffix, e.g. "the partial-update tool" for external-data-schemas-partial-update.
    if any(known.endswith(f"-{name}") for known in registry):
        return True
    # Plural family reference, e.g. "the feature-flag tools".
    if kind in ("tools", "skills") and any(known.startswith(f"{name}-") for known in registry):
        return True
    return False


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _reference_suggestions(name: str, registry: set[str]) -> list[str]:
    """Real names this candidate plausibly meant: exact/suffix matches, else near-misses by edit distance."""
    kebab = name.replace("_", "-")
    suffix = sorted(t for t in registry if t == kebab or t.endswith(f"-{kebab}"))
    if suffix:
        return suffix
    near = sorted((_edit_distance(kebab, known), known) for known in registry)
    return [known for distance, known in near if distance <= _NEAR_MISS_MAX_EDITS]


def _did_you_mean(suggestions: list[str]) -> str:
    return f" — did you mean {' or '.join(suggestions)}?" if suggestions else ""


def _check_tool_references(
    text: str, source_label: str, tool_names: set[str], skill_names: set[str]
) -> list[ReferenceFinding]:
    # Dedupe by name within this text only: one name tripping two rules (e.g. wrong casing inside
    # a phrase) is one finding, but the same stale name in another skill file needs its own.
    findings: list[ReferenceFinding] = []
    reported: set[str] = set()

    def report(offset: int, name: str, message: str) -> None:
        if name in reported:
            return
        reported.add(name)
        line, col = source_files._line_col(text, offset)
        findings.append(ReferenceFinding(source_label, line, col, name, message))

    # "X tool/skill". Resemblance to a real name is the only signal we trust — backticks in prose
    # mean emphasis or a field name as often as a reference, so they are not treated as intent.
    for m in _PHRASE_REFERENCE_RE.finditer(text):
        name, kind = m.group(1), cast("ReferenceKind", m.group(2))
        if _is_valid_reference(name, kind, tool_names, skill_names):
            continue
        suggestions = _reference_suggestions(name, skill_names if kind in ("skill", "skills") else tool_names)
        if suggestions:
            report(
                m.start(1),
                name,
                f"'{name}' looks like a {kind.rstrip('s')} but none exists{_did_you_mean(suggestions)}",
            )
    # "via `X`": one concrete thing, but not whether tool or skill — check tools (a family prefix
    # like `feature-flag` is not invocable) plus exact skill names.
    for m in _INVOCATION_REFERENCE_RE.finditer(text):
        if _ENTITY_NOUN_RE.match(text, m.end()):
            continue
        name = m.group(1)
        if _is_valid_reference(name, "tool", tool_names, skill_names) or name in skill_names:
            continue
        suggestions = _reference_suggestions(name, tool_names)
        if suggestions:
            report(m.start(1), name, f"'{name}' looks like a tool but none exists{_did_you_mean(suggestions)}")
    for m in _CALL_REFERENCE_RE.finditer(text):
        name = m.group(1)
        if _is_valid_reference(name, "tool", tool_names, skill_names):
            continue
        suggestions = _reference_suggestions(name, tool_names)
        if suggestions:
            report(m.start(1), name, f"'{name}' looks like a tool but none exists{_did_you_mean(suggestions)}")
    for m in _SNAKE_CASE_REFERENCE_RE.finditer(text):
        name = m.group(1)
        if name not in tool_names and name.replace("_", "-") in tool_names:
            report(m.start(1), name, f"'{name}' has wrong casing — the tool is named {name.replace('_', '-')}")
    return findings


def _emit_reference_findings(findings: list[ReferenceFinding]) -> None:
    """Surface advisory reference findings without failing the lint.

    In GitHub Actions, emit a workflow warning command so each finding renders as an annotation on
    the offending line in the PR diff; locally, print a plain ``file:line:col`` warning.
    """
    if not findings:
        return
    in_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    for f in findings:
        if in_github_actions:
            print(
                f"::warning file={f.source_label},line={f.line},col={f.col},title=Possible stale reference::{f.message}"
            )
        else:
            print(f"{f.source_label}:{f.line}:{f.col}: warning: {f.message}", file=sys.stderr)
    print(
        f"\nNote: {len(findings)} possible stale tool/skill reference(s) flagged above (advisory, not blocking).",
        file=sys.stderr,
    )
