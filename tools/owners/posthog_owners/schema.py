"""Dataclass model, parser, and validator for ``owners.yaml``.

Also loads ``products/<name>/product.yaml`` as an *aliased* ownership file: only
its ``owners:`` list is read (``@handles`` kept, a ``team-CHANGEME``-only list
treated as empty), every other field ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeGuard

import yaml

from .matcher import compile_pattern

VALID_STATUSES = ("active", "deprecated", "generated", "vendored")
CHANGEME_SLUG = "team-CHANGEME"

# Top-level keys allowed in owners.yaml. Rules allow the same set minus `version`
# and `rules`, plus the required `match`. `teams` is root-only (see parse).
_TOP_LEVEL_KEYS = {"version", "owners", "status", "inherit", "rules", "teams"}
_RULE_KEYS = {"match", "owners", "status", "inherit"}
_TEAMS_ENTRY_KEYS = {"slack"}


class _Unset:
    """Sentinel marking a field the file did not set (so it falls through to an
    ancestor). Distinct from ``owners: null`` (explicit unowned-by-design)."""

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass
class OwnersRule:
    """A per-path override inside a file, evaluated last-match-wins within the file."""

    match: str
    owners: list[str] | None | _Unset = UNSET
    status: str | _Unset = UNSET
    inherit: bool | _Unset = UNSET


@dataclass
class OwnersFile:
    """A parsed ownership file (real ``owners.yaml`` or an aliased ``product.yaml``)."""

    path: Path
    directory: str  # repo-relative posix dir containing the file ("" for repo root)
    owners: list[str] | None  # required; None = explicit unowned-by-design; [] = no contribution
    version: int = 1
    status: str | _Unset = UNSET
    inherit: bool = True
    rules: list[OwnersRule] = field(default_factory=list)
    is_alias: bool = False
    # Root-only Slack registry: team slug -> slack (string or False). Empty everywhere
    # but the repo-root file; lets a team declare its channel once instead of per file.
    teams: dict[str, str | bool] = field(default_factory=dict)


def normalize_product_owners(owners: list[str]) -> list[str]:
    """Drop the ``team-CHANGEME`` scaffold placeholder: it never carries ownership
    signal, so a list consisting only of it is empty. Applied to both ``product.yaml``
    aliases and ``owners.yaml`` owners lists — one CHANGEME semantics everywhere."""
    return [o for o in owners if o != CHANGEME_SLUG]


def _validate_owners_value(value: object, where: str, errors: list[str]) -> list[str] | None | _Unset:
    if value is None:
        return None
    if isinstance(value, str) and value:
        value = [value]
    # Empty-string entries are rejected, not filtered: `owners: ['']` would count
    # as covered while the assigner drops the falsy owner and requests nobody.
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        errors.append(f"{where}: 'owners' must be a non-empty string, a list of non-empty strings, or null")
        return UNSET
    return normalize_product_owners([str(x) for x in value])


def _is_valid_slack(raw: object) -> TypeGuard[str | bool]:
    """A Slack channel value is a string starting with '#', or ``false`` for "no
    channel". Shared by the ``teams:`` registry — the only place a channel is set."""
    return raw is False or (isinstance(raw, str) and raw.startswith("#"))


def _validate_teams(value: object, errors: list[str]) -> dict[str, str | bool]:
    """Validate the root-only ``teams:`` registry — a mapping of team slug to a
    single ``slack`` value."""
    registry: dict[str, str | bool] = {}
    if not isinstance(value, dict):
        errors.append("'teams' must be a mapping of team slug to {slack: ...}")
        return registry
    for slug, entry in value.items():
        where = f"teams['{slug}']"
        if not isinstance(slug, str):
            errors.append(f"teams: slug must be a string, got {slug!r}")
            continue
        if slug.startswith("@"):
            errors.append(f"{where}: registry keys are team slugs, not @handles")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{where}: entry must be a mapping with a 'slack' key")
            continue
        for key in entry:
            if key not in _TEAMS_ENTRY_KEYS:
                errors.append(f"{where}: unknown field '{key}'")
        if "slack" in entry:
            raw = entry["slack"]
            if _is_valid_slack(raw):
                registry[slug] = raw
            else:
                errors.append(f"{where}: 'slack' must be a string starting with '#' or false")
    return registry


def _validate_status(value: object, where: str, errors: list[str]) -> str | _Unset:
    if isinstance(value, str) and value in VALID_STATUSES:
        return value
    errors.append(f"{where}: 'status' must be one of {', '.join(VALID_STATUSES)}")
    return UNSET


def _validate_inherit(value: object, where: str, errors: list[str]) -> bool | _Unset:
    if isinstance(value, bool):
        return value
    errors.append(f"{where}: 'inherit' must be a boolean")
    return UNSET


def _rule_match_patterns(raw_match: object, where: str, errors: list[str]) -> list[str]:
    """A rule's ``match`` may be one non-empty string or a non-empty list of them.
    Returns every compiling pattern in order; on any malformed or uncompilable entry
    it appends a schema error and returns ``[]`` so the whole rule is dropped (lint
    reports a normal error and the resolver never sees a rule that would crash)."""
    if isinstance(raw_match, str):
        candidates: list[object] = [raw_match]
    elif isinstance(raw_match, list) and raw_match:
        candidates = list(raw_match)
    else:
        errors.append(f"{where}: 'match' is required and must be a non-empty string or a non-empty list of strings")
        return []

    patterns: list[str] = []
    ok = True
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            errors.append(f"{where}: each 'match' pattern must be a non-empty string")
            ok = False
            continue
        try:
            compile_pattern(candidate)
        except ValueError as exc:
            errors.append(f"{where}: invalid match pattern '{candidate}': {exc}")
            ok = False
            continue
        patterns.append(candidate)
    return patterns if ok else []


def _parse_rule(raw: object, index: int, errors: list[str]) -> list[OwnersRule]:
    """Parse one physical rule entry into one ``OwnersRule`` per ``match`` pattern
    (a list ``match`` explodes here so resolver/fmt/lint keep seeing single-pattern
    rules). Returns ``[]`` on a schema error."""
    where = f"rules[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}: each rule must be a mapping")
        return []
    for key in raw:
        if key not in _RULE_KEYS:
            errors.append(f"{where}: unknown field '{key}'")
    patterns = _rule_match_patterns(raw.get("match"), where, errors)
    if not patterns:
        return []

    owners = _validate_owners_value(raw["owners"], where, errors) if "owners" in raw else UNSET
    status = _validate_status(raw["status"], where, errors) if "status" in raw else UNSET
    inherit = _validate_inherit(raw["inherit"], where, errors) if "inherit" in raw else UNSET
    return [OwnersRule(match=pattern, owners=owners, status=status, inherit=inherit) for pattern in patterns]


def parse_owners_file(text: str, *, path: Path, directory: str) -> tuple[OwnersFile | None, list[str]]:
    """Parse and validate ``owners.yaml`` contents.

    Returns ``(file, errors)``. ``file`` is None only when the document itself is
    unusable (bad YAML, not a mapping, missing required fields).
    """
    errors: list[str] = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [f"invalid YAML: {exc}"]
    if not isinstance(data, dict):
        return None, ["owners.yaml must be a YAML mapping"]

    for key in data:
        if key not in _TOP_LEVEL_KEYS:
            errors.append(f"unknown top-level field '{key}'")

    if data.get("version") != 1:
        errors.append("'version: 1' is required")

    if "owners" not in data:
        errors.append("'owners' is required (a string, a list of strings, or null for unowned-by-design)")
        owners: list[str] | None = []
    else:
        validated = _validate_owners_value(data["owners"], "owners", errors)
        owners = [] if isinstance(validated, _Unset) else validated

    file = OwnersFile(path=path, directory=directory, owners=owners)

    if "status" in data:
        file.status = _validate_status(data["status"], "status", errors)
    if "inherit" in data:
        inherit = _validate_inherit(data["inherit"], "inherit", errors)
        file.inherit = True if isinstance(inherit, _Unset) else inherit

    if "teams" in data:
        # The registry is a single repo-wide lookup, so it only makes sense at the
        # root; a nested file carrying it would silently do nothing.
        if directory != "":
            errors.append("'teams' is only allowed in the repo-root owners.yaml")
        else:
            file.teams = _validate_teams(data["teams"], errors)

    if "rules" in data:
        raw_rules = data["rules"]
        if not isinstance(raw_rules, list):
            errors.append("'rules' must be a list")
        else:
            for i, raw_rule in enumerate(raw_rules):
                file.rules.extend(_parse_rule(raw_rule, i, errors))

    # A missing version or owners makes the file unusable for resolution.
    if data.get("version") != 1 or "owners" not in data:
        return None, errors
    return file, errors


def parse_product_yaml_as_owners(text: str, *, path: Path, directory: str) -> OwnersFile | None:
    """Load ``product.yaml`` as an aliased ownership file, or None if it has no
    usable ``owners:`` list."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict) or "owners" not in data:
        return None
    raw = data["owners"]
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        return None
    owners = normalize_product_owners(raw)
    return OwnersFile(path=path, directory=directory, owners=owners, is_alias=True)


def match_is_glob(match: str) -> bool:
    """A rule match is a crosscutting glob (not a tree boundary) when it carries a
    wildcard character."""
    return any(ch in match for ch in "*?[")


def is_simple_owners_file(parsed: OwnersFile | None, *, allow_anchored_rules: bool = False) -> bool:
    """Whether a file is "simple" — mechanically relocatable, nothing but ownership.

    Both callers agree that status/``inherit: false`` (and being a
    ``product.yaml`` alias) disqualify a file. So does a ``teams:`` registry:
    it is root-only content relocation would strand. So does any rule carrying
    more than match+owners: relocation only preserves owners, so rule-level
    ``status``/``inherit`` must pin the file. They differ on rules:

    - lint's consolidation suggestions (``allow_anchored_rules=False``) only fold
      files whose entire content is one non-empty ``owners:`` list;
    - fmt (``allow_anchored_rules=True``) reasons about statements, so files whose
      rules are all anchored (no globs) are fair game too.
    """
    if parsed is None or parsed.is_alias:
        return False
    if parsed.inherit is False or parsed.status is not UNSET or parsed.teams:
        return False
    if any(r.status is not UNSET or r.inherit is not UNSET for r in parsed.rules):
        return False
    if allow_anchored_rules:
        return not any(match_is_glob(r.match) for r in parsed.rules)
    return bool(parsed.owners) and not parsed.rules
