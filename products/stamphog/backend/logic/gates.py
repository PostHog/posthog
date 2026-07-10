"""Pure deterministic gate pipeline for stamphog PR review.

Ported from `tools/pr-approval-agent/gates.py`, trimmed to what the review
pipeline needs: prerequisites (draft, merge conflicts, changes-requested),
the deny-list hard gate, the size ceiling, and tier classification. No
network calls - every input (`pr`, `files`, the loaded `policy`) is already
fetched by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from products.stamphog.backend.logic.policy import Policy

_TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?)/|[_.](?:test|spec)\.[^/]+$|_test\.py$",
    re.IGNORECASE,
)

# Files that inflate a diff without adding review surface: prose docs,
# regenerated artifacts, and test snapshots. Excluded from the size ceiling
# but still counted toward tier classification (via the full path list).
SIZE_EXEMPT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".snap",
    ".ambr",
    ".storyshot",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".lock",
}

_SIZE_EXEMPT_PATH_RE = re.compile(
    r"(?:^|/)docs/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|(?:^|/)generated/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|\.gen\.(ts|tsx|js|jsx)$"
    r"|\.generated\.(ts|tsx|js|jsx)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GateInput:
    pr: dict
    files: list[dict]
    policy: Policy
    is_draft: bool
    has_merge_conflicts: bool = False
    has_changes_requested_review: bool = False


@dataclass(frozen=True)
class GateResult:
    passed: bool
    tier: str
    reason: str
    details: dict = field(default_factory=dict)


def _is_size_exempt(path: str) -> bool:
    return Path(path).suffix.lower() in SIZE_EXEMPT_EXTENSIONS or bool(_SIZE_EXEMPT_PATH_RE.search(path))


def _classify_path(path: str) -> str:
    low = path.lower()
    if _TEST_FILE_RE.search(low):
        return "test"
    if low.endswith(".md"):
        return "docs"
    if low.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock")):
        return "config"
    return "other"


def is_allow_listed_only(paths: list[str], policy: Policy) -> bool:
    if not paths:
        return False
    for f in paths:
        low = f.lower()
        if Path(low).suffix in policy.allow_extensions:
            continue
        if any(p.lower() in low for p in policy.allow_path_patterns):
            continue
        return False
    return True


def is_test_only(paths: list[str]) -> bool:
    if not paths:
        return False
    return all(_classify_path(p) == "test" for p in paths)


def scope_breadth(paths: list[str]) -> str:
    top_dirs = {p.split("/")[0] for p in paths if "/" in p}
    if len(top_dirs) <= 1:
        return "single-area"
    if len(top_dirs) == 2:
        return "two-areas"
    return "cross-cutting"


def _compile_deny_pattern(pattern: str) -> re.Pattern[str]:
    """Compile one deny pattern into a case-insensitive path regex.

    Patterns containing a path separator or starting with a dot are treated
    as literal path fragments (no boundaries). Others get boundaries that
    also break on `_`/`-`, since paths use those as word separators (so
    "secret" matches "secret_key_store.py" but not "nosecrets.py").
    """
    if "/" in pattern or pattern.startswith(r"\."):
        return re.compile(rf"(?i){pattern}")
    return re.compile(rf"(?i)(?<![a-zA-Z0-9]){pattern}(?![a-zA-Z0-9])")


def detect_deny_categories(paths: list[str], policy: Policy) -> list[str]:
    """Categories hard-denied by the changed file paths."""
    hits: set[str] = set()
    for category, spec in policy.deny.items():
        regexes = [_compile_deny_pattern(p) for p in spec.match_paths]
        candidate_paths = [p.lower() for p in paths if not p.lower().startswith(spec.exempt_path_prefixes)]
        if any(rx.search(p) for rx in regexes for p in candidate_paths):
            hits.add(category)
    return sorted(hits)


def substantive_size(files: list[dict]) -> tuple[int, int]:
    """(changed lines, file count) over the files that count toward the size ceiling."""
    counted = [f for f in files if not _is_size_exempt(f["filename"])]
    return sum(f["additions"] + f["deletions"] for f in counted), len(counted)


def _group_by_folder_scope(paths: list[str], policy: Policy) -> dict[str, list[str]]:
    """Group counted paths by their governing AGENT_APPROVALS.md folder, if any.

    A path is governed by the nearest (longest) folder override that is an
    ancestor of it. Ungoverned paths pool into the global scope (key `""`),
    which is always checked against `policy.size_gate.max_files`.
    """
    folders_by_length = sorted(policy.folder_max_files, key=len, reverse=True)
    scopes: dict[str, list[str]] = {}
    for path in paths:
        folder = next((f for f in folders_by_length if path == f or path.startswith(f + "/")), "")
        scopes.setdefault(folder, []).append(path)
    return scopes


def check_size_gate(files: list[dict], policy: Policy) -> tuple[bool, str]:
    """Hard size gate: total changed lines, and per-scope changed file counts.

    `max_lines` is a single global total, never delegable to a folder
    override. Per-scope file counts are checked against that scope's own
    ceiling - a folder's AGENT_APPROVALS.md grant only widens the ceiling for
    files under that folder, never for the whole PR.
    """
    lines_total, _ = substantive_size(files)
    if lines_total > policy.size_gate.max_lines:
        return False, f"{lines_total} changed lines exceeds the {policy.size_gate.max_lines}-line ceiling"

    counted_paths = [f["filename"] for f in files if not _is_size_exempt(f["filename"])]
    scopes = _group_by_folder_scope(counted_paths, policy)
    for folder, scoped_paths in scopes.items():
        ceiling = policy.folder_max_files.get(folder, policy.size_gate.max_files)
        if len(scoped_paths) > ceiling:
            scope_label = folder or "global"
            return (
                False,
                f"{len(scoped_paths)} changed files in scope {scope_label!r} exceeds the {ceiling}-file ceiling",
            )
    return True, ""


def _breadth_within(rule: str, breadth: str) -> bool:
    """Whether a PR's breadth satisfies a sub-tier's breadth rule.

    `single-area` requires an exact match; `not-cross-cutting` admits
    anything but a cross-cutting change.
    """
    if rule == "single-area":
        return breadth == "single-area"
    return breadth != "cross-cutting"


def t1_risk_subclass(*, lines_total: int, files_changed: int, breadth: str, policy: Policy) -> str:
    # First matching sub-tier wins (policy order is narrowest first); T1d is
    # the fallback for anything past the largest configured sub-tier.
    for label, sub in policy.t1_subclasses.items():
        if lines_total <= sub.max_lines and files_changed <= sub.max_files and _breadth_within(sub.breadth, breadth):
            return label
    return "T1d-complex"


def assign_tier(
    *,
    deny_categories: list[str],
    allow_listed_only: bool,
    is_test_only: bool,
    lines_total: int,
    files_changed: int,
    breadth: str,
    policy: Policy,
) -> str:
    if deny_categories:
        return "T2-never"
    if allow_listed_only or is_test_only:
        return "T0-deterministic"
    return t1_risk_subclass(lines_total=lines_total, files_changed=files_changed, breadth=breadth, policy=policy)


def run_gates(gate_input: GateInput) -> GateResult:
    """Run the deterministic gate pipeline: prerequisites, deny-list, size, tier.

    Prerequisites and the deny-list are hard gates that short-circuit
    immediately. The size gate still computes tier/breadth details so the
    caller has classification context even on a failed gate.
    """
    if gate_input.is_draft:
        return GateResult(passed=False, tier="T2-never", reason="PR is a draft")
    if gate_input.has_merge_conflicts:
        return GateResult(passed=False, tier="T2-never", reason="PR has merge conflicts")
    if gate_input.has_changes_requested_review:
        return GateResult(passed=False, tier="T2-never", reason="PR has an outstanding changes-requested review")

    paths = [f["filename"] for f in gate_input.files]
    policy = gate_input.policy

    deny_categories = detect_deny_categories(paths, policy)
    if deny_categories:
        return GateResult(
            passed=False,
            tier="T2-never",
            reason=f"deny-listed categories: {', '.join(deny_categories)}",
            details={"deny_categories": deny_categories},
        )

    lines_total, files_changed = substantive_size(gate_input.files)
    allow_listed_only = is_allow_listed_only(paths, policy)
    test_only = is_test_only(paths)
    breadth = scope_breadth(paths)
    tier = assign_tier(
        deny_categories=deny_categories,
        allow_listed_only=allow_listed_only,
        is_test_only=test_only,
        lines_total=lines_total,
        files_changed=files_changed,
        breadth=breadth,
        policy=policy,
    )
    details = {
        "lines_total": lines_total,
        "files_changed": files_changed,
        "breadth": breadth,
        "allow_listed_only": allow_listed_only,
        "is_test_only": test_only,
    }

    size_ok, size_reason = check_size_gate(gate_input.files, policy)
    if not size_ok:
        return GateResult(passed=False, tier=tier, reason=size_reason, details=details)

    return GateResult(passed=True, tier=tier, reason="passed all deterministic gates", details=details)
