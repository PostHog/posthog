"""Dataclass model, parser, and validator for ``owners.yaml``.

Also loads an *alias* file as an ownership file: only its ``owners:`` list is read
(``@handles`` kept, a ``team-CHANGEME``-only list treated as empty), every other field
ignored. The root file names the alias files in ``alias_files``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeGuard

import yaml

from .matcher import compile_pattern

VALID_STATUSES = ("active", "deprecated", "generated", "vendored")
CHANGEME_SLUG = "team-CHANGEME"
OWNERS_FILENAME = "owners.yaml"

# Keys that only the repo-root owners.yaml may carry. They describe the repo, not a directory.
ROOT_ONLY_KEYS = {"teams", "github_org", "producers", "reserved_dirs", "codeowners", "alias_files"}
# Top-level keys allowed in owners.yaml. Rules allow the same set minus `version`
# and `rules`, plus the required `match`.
TOP_LEVEL_KEYS = {"version", "owners", "status", "inherit", "rules"} | ROOT_ONLY_KEYS
_RULE_KEYS = {"match", "owners", "status", "inherit"}
# Every alias name is one more file to read per directory, and a hosted resolver reads a root file
# it does not control, so the list has a ceiling.
MAX_ALIAS_FILES = 8
_TEAMS_ENTRY_KEYS = {"slack", "notifications"}
_CODEOWNERS_KEYS = {"jest_root", "jest_root_tests", "jest_root_packages"}

# The name of an automation that posts to a team's notifications channel, such as a review bot.
# When the root file declares a `producers:` list, only a declared producer is nameable in
# `notifications:`, so a typo is an error. Lint reports it where lint runs; where it does not, an
# unreadable mapping silences rather than posts (see _validate_teams).
Producer = str


@dataclass(frozen=True)
class TeamEntry:
    """One team's entry in the root ``teams:`` registry.

    ``slack`` is where people are. ``notifications`` is where automation posts, and it falls back
    to ``slack`` when a team never separates the two.

    ``notifications`` may also be a mapping of producer name to channel, so a team can silence or
    redirect one bot without doing it to all of them. A producer the mapping does not name falls
    through to ``slack``.

    ``None`` means the key was not declared, which is not the same as ``False``. The first falls
    through to the next step of the lookup; the second is a decision that there is no channel.
    """

    slack: str | bool | None = None
    notifications: str | bool | Mapping[str, str | bool] | None = None


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


@dataclass(frozen=True)
class CodeownersSettings:
    """How the CODEOWNERS projection spells test paths.

    A Jest project can run the tests of other packages from its own directory. Its JUnit report
    then spells those files relative to ``jest_root``. ``jest_root_tests`` is a glob of the test
    files that run that way. ``jest_root_packages`` names the tree whose packages never run their
    own suite, so their files get no package-relative spelling.
    """

    jest_root: str | None = None
    jest_root_tests: str | None = None
    jest_root_packages: str | None = None


@dataclass(frozen=True)
class RepoSettings:
    """Repo-wide settings from the root ``owners.yaml``.

    ``github_org`` turns a team slug into ``@org/slug`` and scopes the live lint. ``producers``
    lists the automation names a team may address in ``notifications:``; ``None`` means the repo
    declared no list, so any name is accepted. ``reserved_dirs`` lists
    globs where an ``owners.yaml`` must not live, because other tooling reads every YAML file there.
    ``alias_files`` lists the other file names that count as ownership files, in the order that
    decides which one wins when a directory holds several.
    """

    github_org: str | None = None
    producers: frozenset[str] | None = None
    reserved_dirs: tuple[str, ...] = ()
    alias_files: tuple[str, ...] = ()
    codeowners: CodeownersSettings = field(default_factory=CodeownersSettings)


@dataclass
class OwnersRule:
    """A per-path override inside a file, evaluated last-match-wins within the file."""

    match: str
    owners: list[str] | None | _Unset = UNSET
    status: str | _Unset = UNSET
    inherit: bool | _Unset = UNSET


@dataclass
class OwnersFile:
    """A parsed ownership file (a real ``owners.yaml`` or an alias file)."""

    path: Path
    directory: str  # repo-relative posix dir containing the file ("" for repo root)
    owners: list[str] | None  # required; None = explicit unowned-by-design; [] = no contribution
    version: int = 1
    status: str | _Unset = UNSET
    inherit: bool = True
    rules: list[OwnersRule] = field(default_factory=list)
    is_alias: bool = False
    # Root-only Slack registry: team slug -> TeamEntry. Empty everywhere but the repo-root
    # file; lets a team declare its channels once instead of per file.
    teams: dict[str, TeamEntry] = field(default_factory=dict)
    settings: RepoSettings = field(default_factory=RepoSettings)


def normalize_owners(owners: list[str]) -> list[str]:
    """Drop the ``team-CHANGEME`` scaffold placeholder: it never carries ownership
    signal, so a list consisting only of it is empty. Applied to both alias files
    and ``owners.yaml`` owners lists — one CHANGEME semantics everywhere."""
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
    return normalize_owners([str(x) for x in value])


def _is_valid_slack(raw: object) -> TypeGuard[str | bool]:
    """A Slack channel value is a string starting with '#', or ``false`` for "no
    channel". Shared by every key in the ``teams:`` registry."""
    return raw is False or (isinstance(raw, str) and raw.startswith("#"))


def _validate_producer_map(
    value: dict[object, object], where: str, key: str, producers: frozenset[str] | None, errors: list[str]
) -> dict[str, str | bool]:
    """The producers a ``notifications:`` mapping names, without the entries it rejects."""
    if key != "notifications":
        errors.append(f"{where}: '{key}' takes a single channel, not a per-producer mapping")
        return {}
    if not value:
        errors.append(f"{where}: '{key}' mapping names no producer")
        return {}
    declared: dict[str, str | bool] = {}
    for producer, raw in value.items():
        if not isinstance(producer, str) or not producer:
            errors.append(f"{where}: producer names must be non-empty strings, got {producer!r}")
        elif producers is not None and producer not in producers:
            known = ", ".join(sorted(producers))
            errors.append(f"{where}: unknown producer '{producer}' (declared in 'producers': {known})")
        elif _is_valid_slack(raw):
            declared[producer] = raw
        else:
            errors.append(f"{where}: '{producer}' must be a string starting with '#' or false")
    return declared


def _validate_teams(value: object, producers: frozenset[str] | None, errors: list[str]) -> dict[str, TeamEntry]:
    """Validate the root-only ``teams:`` registry, a mapping of team slug to its channels.

    A slug registers only when it declares at least one channel. Membership of the returned
    mapping therefore means "this repo answered for that team", and nothing more.
    """
    known_keys = ", ".join(sorted(_TEAMS_ENTRY_KEYS))
    registry: dict[str, TeamEntry] = {}
    if not isinstance(value, dict):
        errors.append(f"'teams' must be a mapping of team slug to a mapping of {{{known_keys}}}")
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
            errors.append(f"{where}: entry must be a mapping with a {known_keys} key")
            continue
        declared: dict[str, str | bool | Mapping[str, str | bool]] = {}
        for key, raw in entry.items():
            if not isinstance(key, str) or key not in _TEAMS_ENTRY_KEYS:
                errors.append(f"{where}: unknown field '{key}'")
            elif isinstance(raw, dict):
                per_producer = _validate_producer_map(raw, where, key, producers, errors)
                if per_producer:
                    declared[key] = per_producer
                elif key == "notifications":
                    # A mapping we could not read silences the producer. Dropping the key would
                    # post to the channel the team asked to be left out of, and a repo we read
                    # this file from over the API runs no lint of ours.
                    declared[key] = False
            elif _is_valid_slack(raw):
                declared[key] = raw
            else:
                errors.append(f"{where}: '{key}' must be a string starting with '#' or false")
        if declared:
            registry[slug] = TeamEntry(**declared)
    return registry


def _validate_string_list(value: object, key: str, errors: list[str]) -> list[str]:
    if isinstance(value, list) and all(isinstance(x, str) and x for x in value):
        return [str(x) for x in value]
    errors.append(f"'{key}' must be a list of non-empty strings")
    return []


def _validate_codeowners(value: object, errors: list[str]) -> CodeownersSettings:
    if not isinstance(value, dict):
        errors.append(f"'codeowners' must be a mapping with keys {', '.join(sorted(_CODEOWNERS_KEYS))}")
        return CodeownersSettings()
    declared: dict[str, str] = {}
    for key, raw in value.items():
        if key not in _CODEOWNERS_KEYS:
            errors.append(f"codeowners: unknown field '{key}'")
        elif not isinstance(raw, str) or not raw:
            errors.append(f"codeowners: '{key}' must be a non-empty string")
        elif key == "jest_root_tests":
            try:
                compile_pattern(raw)
            except ValueError as exc:
                errors.append(f"codeowners: invalid jest_root_tests pattern '{raw}': {exc}")
                continue
            declared[key] = raw
        else:
            declared[key] = raw.strip("/")
    return CodeownersSettings(**declared)


def _validate_settings(data: dict[object, object], errors: list[str]) -> RepoSettings:
    """Read the root-only repo settings. An invalid value is reported and left at its default."""
    github_org: str | None = None
    if "github_org" in data:
        raw_org = data["github_org"]
        if isinstance(raw_org, str) and raw_org and "/" not in raw_org:
            github_org = raw_org
        else:
            errors.append("'github_org' must be a GitHub organization name, such as 'my-org'")

    producers = (
        frozenset(_validate_string_list(data["producers"], "producers", errors)) if "producers" in data else None
    )

    reserved_dirs: list[str] = []
    for pattern in (
        _validate_string_list(data["reserved_dirs"], "reserved_dirs", errors) if "reserved_dirs" in data else []
    ):
        try:
            compile_pattern(pattern)
        except ValueError as exc:
            errors.append(f"reserved_dirs: invalid pattern '{pattern}': {exc}")
            continue
        reserved_dirs.append(pattern)

    alias_files: list[str] = []
    for name in _validate_string_list(data["alias_files"], "alias_files", errors) if "alias_files" in data else []:
        if "/" in name:
            errors.append(f"alias_files: '{name}' must be a bare file name, without '/'")
            continue
        if name == OWNERS_FILENAME:
            errors.append(f"alias_files: '{OWNERS_FILENAME}' is the ownership file, not an alias")
            continue
        alias_files.append(name)
    if len(alias_files) > MAX_ALIAS_FILES:
        errors.append(f"alias_files: at most {MAX_ALIAS_FILES} names are allowed")
        alias_files = []

    codeowners = _validate_codeowners(data["codeowners"], errors) if "codeowners" in data else CodeownersSettings()
    return RepoSettings(
        github_org=github_org,
        producers=producers,
        reserved_dirs=tuple(reserved_dirs),
        alias_files=tuple(alias_files),
        codeowners=codeowners,
    )


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


def _is_version_one(value: object) -> bool:
    """YAML ``true`` and ``1.0`` compare equal to 1 in Python, but the format requires the integer."""
    return type(value) is int and value == 1


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
        if key not in TOP_LEVEL_KEYS:
            errors.append(f"unknown top-level field '{key}'")

    version_ok = _is_version_one(data.get("version"))
    if not version_ok:
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

    # Repo-wide settings and the team registry are single lookups, so they only make sense at
    # the root; a nested file carrying them would silently do nothing.
    if directory != "":
        for key in sorted(ROOT_ONLY_KEYS & data.keys()):
            errors.append(f"'{key}' is only allowed in the repo-root owners.yaml")
    else:
        file.settings = _validate_settings(data, errors)
        if "teams" in data:
            file.teams = _validate_teams(data["teams"], file.settings.producers, errors)

    if "rules" in data:
        raw_rules = data["rules"]
        if not isinstance(raw_rules, list):
            errors.append("'rules' must be a list")
        else:
            for i, raw_rule in enumerate(raw_rules):
                file.rules.extend(_parse_rule(raw_rule, i, errors))

    # A missing version or owners makes the file unusable for resolution.
    if not version_ok or "owners" not in data:
        return None, errors
    return file, errors


def parse_alias_file_as_owners(text: str, *, path: Path, directory: str) -> OwnersFile | None:
    """Load an alias file as an ownership file, or None if it has no
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
    owners = normalize_owners(raw)
    return OwnersFile(path=path, directory=directory, owners=owners, is_alias=True)


def match_is_glob(match: str) -> bool:
    """A rule match is a crosscutting glob (not a tree boundary) when it carries a
    wildcard character."""
    return any(ch in match for ch in "*?[")


def is_simple_owners_file(parsed: OwnersFile | None, *, allow_anchored_rules: bool = False) -> bool:
    """Whether a file is "simple" — mechanically relocatable, nothing but ownership.

    Both callers agree that status/``inherit: false`` (and being an
    alias file) disqualify a file. So does a ``teams:`` registry:
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
