"""Parses `.stamphog/policy.yml` semantics for the gate pipeline.

Ported from `tools/pr-approval-agent/policy.py`, trimmed to what the
deterministic gate pipeline needs: deny-list categories, the allow-list,
size ceilings, tier subclasses, and per-folder `AGENT_APPROVALS.md` size-gate
overrides. Dismiss-time data, familiarity bands, and ownership sources stay
out - those are advisory/CLI-only concerns the review pipeline doesn't gate on.

This module never touches the filesystem or the network: `load_policy` takes
every file's content already fetched by the caller (github_client.py), keyed
by repo-relative path. Policy files are fetched from the target repo's
DEFAULT BRANCH, never the PR head, so a PR can't edit its own gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

POLICY_PATH = ".stamphog/policy.yml"

_FOLDER_OVERRIDE_FILENAME = "AGENT_APPROVALS.md"
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


class PolicyError(ValueError):
    """Raised when the fetched policy YAML is missing or malformed - fail closed."""


@dataclass(frozen=True)
class DenyCategory:
    description: str
    # Patterns matched against file paths only (hard deny). PR-title-only
    # scrutiny flags from the legacy tool are dropped here - this pipeline
    # only needs a pass/fail gate, not LLM-prompt calibration.
    match_paths: tuple[str, ...]
    exempt_path_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SizeGate:
    max_lines: int
    max_files: int


@dataclass(frozen=True)
class T1Subclass:
    max_lines: int
    max_files: int
    breadth: str  # "single-area" or "not-cross-cutting"


@dataclass(frozen=True)
class Policy:
    deny: dict[str, DenyCategory]
    allow_path_patterns: tuple[str, ...]
    allow_extensions: frozenset[str]
    size_gate: SizeGate
    t1_subclasses: dict[str, T1Subclass]
    # Folder path (repo-relative, no trailing slash) -> delegated max_files,
    # read from that folder's AGENT_APPROVALS.md and capped at the policy's
    # declared overrides."size_gate.max_files".ceiling.
    folder_max_files: dict[str, int] = field(default_factory=dict)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PolicyError(message)


def _parse_deny(raw: Any) -> dict[str, DenyCategory]:
    _require(isinstance(raw, dict) and bool(raw), "deny: must be a non-empty mapping")
    deny: dict[str, DenyCategory] = {}
    for category, spec in raw.items():
        _require(isinstance(spec, dict), f"deny.{category}: must be a mapping")
        match = spec.get("match")
        _require(isinstance(match, dict) and bool(match), f"deny.{category}.match: must be a non-empty mapping")
        # "paths" and "any" both hard-deny on file paths; "titles" (PR-title
        # only scrutiny) is intentionally not read here.
        path_patterns: list[str] = list(match.get("paths", [])) + list(match.get("any", []))
        _require(bool(path_patterns), f"deny.{category}.match: must declare 'paths' or 'any' patterns")
        for pattern in path_patterns:
            _require(isinstance(pattern, str), f"deny.{category}.match: patterns must be strings")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise PolicyError(f"deny.{category}.match: pattern {pattern!r} does not compile: {exc}") from exc
        exempt = spec.get("exempt_path_prefixes", [])
        _require(isinstance(exempt, list), f"deny.{category}.exempt_path_prefixes: must be a list")
        deny[category] = DenyCategory(
            description=str(spec.get("description", "")),
            match_paths=tuple(path_patterns),
            exempt_path_prefixes=tuple(str(p) for p in exempt),
        )
    return deny


def _parse_allow(raw: Any) -> tuple[tuple[str, ...], frozenset[str]]:
    _require(isinstance(raw, dict), "allow: must be a mapping")
    path_patterns = raw.get("path_patterns")
    extensions = raw.get("extensions_only")
    _require(isinstance(path_patterns, list) and bool(path_patterns), "allow.path_patterns: must be a non-empty list")
    _require(isinstance(extensions, list) and bool(extensions), "allow.extensions_only: must be a non-empty list")
    return tuple(str(p) for p in path_patterns), frozenset(str(e) for e in extensions)


def _parse_size_gate(raw: Any) -> SizeGate:
    _require(isinstance(raw, dict), "size_gate: must be a mapping")
    max_lines, max_files = raw.get("max_lines"), raw.get("max_files")
    _require(isinstance(max_lines, int) and not isinstance(max_lines, bool), "size_gate.max_lines: must be an integer")
    _require(isinstance(max_files, int) and not isinstance(max_files, bool), "size_gate.max_files: must be an integer")
    return SizeGate(max_lines=max_lines, max_files=max_files)


def _parse_tiers(raw: Any) -> dict[str, T1Subclass]:
    _require(isinstance(raw, dict), "tiers: must be a mapping")
    subclasses_raw = raw.get("t1_subclasses")
    _require(
        isinstance(subclasses_raw, dict) and bool(subclasses_raw),
        "tiers.t1_subclasses: must be a non-empty mapping",
    )
    subclasses: dict[str, T1Subclass] = {}
    for name, spec in subclasses_raw.items():
        _require(isinstance(spec, dict), f"tiers.t1_subclasses.{name}: must be a mapping")
        max_lines, max_files, breadth = spec.get("max_lines"), spec.get("max_files"), spec.get("breadth")
        _require(
            isinstance(max_lines, int) and not isinstance(max_lines, bool), f"{name}.max_lines: must be an integer"
        )
        _require(
            isinstance(max_files, int) and not isinstance(max_files, bool), f"{name}.max_files: must be an integer"
        )
        _require(breadth in ("single-area", "not-cross-cutting"), f"{name}.breadth: invalid value {breadth!r}")
        subclasses[name] = T1Subclass(max_lines=max_lines, max_files=max_files, breadth=breadth)
    return subclasses


def _override_ceiling(overrides_raw: Any, key: str) -> int | None:
    if not isinstance(overrides_raw, dict):
        return None
    spec = overrides_raw.get(key)
    if not isinstance(spec, dict):
        return None
    ceiling = spec.get("ceiling")
    if not isinstance(ceiling, int) or isinstance(ceiling, bool):
        return None
    return ceiling


def _parse_folder_overrides(files: dict[str, str], max_files_ceiling: int | None) -> dict[str, int]:
    """Read delegated `size_gate.max_files` from every fetched AGENT_APPROVALS.md.

    Positive allow-list, same posture as the legacy CLI tool: only the
    `size_gate.max_files` key is honored, capped at the policy's declared
    ceiling. Anything else (missing frontmatter, undelegated keys, no ceiling
    declared) contributes nothing rather than raising - a malformed folder
    file must not crash the pipeline, only fail to grant leniency.
    """
    if max_files_ceiling is None:
        return {}
    overrides: dict[str, int] = {}
    for path, content in files.items():
        if not path.endswith(_FOLDER_OVERRIDE_FILENAME):
            continue
        match = _FRONTMATTER_RE.match(content)
        if match is None:
            continue
        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if not isinstance(frontmatter, dict):
            continue
        stamphog = frontmatter.get("stamphog")
        if not isinstance(stamphog, dict) or set(stamphog) != {"size_gate"}:
            continue
        size_gate = stamphog["size_gate"]
        if not isinstance(size_gate, dict) or set(size_gate) != {"max_files"}:
            continue
        value = size_gate["max_files"]
        if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= max_files_ceiling):
            continue
        folder = str(PurePosixPath(path).parent)
        overrides[folder] = value
    return overrides


def load_policy(files: dict[str, str]) -> Policy:
    """Parse `.stamphog/policy.yml` from fetched default-branch content.

    `files` maps repo-relative path -> file content, fetched from the target
    repo's default branch (never PR head) - this keeps the policy itself
    immune to a PR editing its own gate. Raises PolicyError on any malformed
    input - fail closed, the caller must not gate on a half-loaded policy.
    """
    raw_text = files.get(POLICY_PATH)
    _require(raw_text is not None, f"policy: {POLICY_PATH} not found in fetched files")
    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise PolicyError(f"policy: could not parse {POLICY_PATH}: {exc}") from exc
    _require(isinstance(raw, dict), "policy root: must be a mapping")

    for required in ("deny", "allow", "size_gate", "tiers"):
        _require(required in raw, f"policy root: missing required section {required!r}")

    allow_path_patterns, allow_extensions = _parse_allow(raw["allow"])
    max_files_ceiling = _override_ceiling(raw.get("overrides"), "size_gate.max_files")
    return Policy(
        deny=_parse_deny(raw["deny"]),
        allow_path_patterns=allow_path_patterns,
        allow_extensions=allow_extensions,
        size_gate=_parse_size_gate(raw["size_gate"]),
        t1_subclasses=_parse_tiers(raw["tiers"]),
        folder_max_files=_parse_folder_overrides(files, max_files_ceiling),
    )
