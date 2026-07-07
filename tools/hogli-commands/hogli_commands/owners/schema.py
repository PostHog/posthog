"""Dataclass model, parser, and validator for ``owners.yaml``.

Also loads ``products/<name>/product.yaml`` as an *aliased* ownership file: only
its ``owners:`` list is read (``@handles`` kept, a ``team-CHANGEME``-only list
treated as empty), every other field ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_STATUSES = ("active", "deprecated", "generated", "vendored")
CHANGEME_SLUG = "team-CHANGEME"

# Top-level keys allowed in owners.yaml. Rules allow the same set minus `version`
# and `rules`, plus the required `match`.
_TOP_LEVEL_KEYS = {"version", "owners", "contact", "status", "inherit", "rules"}
_RULE_KEYS = {"match", "owners", "contact", "status", "inherit"}
_CONTACT_KEYS = {"slack", "oncall"}


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
    slack: str | bool | _Unset = UNSET
    oncall: str | _Unset = UNSET
    status: str | _Unset = UNSET
    inherit: bool | _Unset = UNSET


@dataclass
class OwnersFile:
    """A parsed ownership file (real ``owners.yaml`` or an aliased ``product.yaml``)."""

    path: Path
    directory: str  # repo-relative posix dir containing the file ("" for repo root)
    owners: list[str] | None  # required; None = explicit unowned-by-design; [] = no contribution
    version: int = 1
    slack: str | bool | _Unset = UNSET
    oncall: str | _Unset = UNSET
    status: str | _Unset = UNSET
    inherit: bool = True
    rules: list[OwnersRule] = field(default_factory=list)
    is_alias: bool = False


def _validate_owners_value(value: object, where: str, errors: list[str]) -> list[str] | None | _Unset:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        errors.append(f"{where}: 'owners' must be a list of strings or null")
        return UNSET
    owners: list[str] = [str(x) for x in value]
    return owners


def _validate_contact(value: object, where: str, errors: list[str]) -> tuple[str | bool | _Unset, str | _Unset]:
    slack: str | bool | _Unset = UNSET
    oncall: str | _Unset = UNSET
    if not isinstance(value, dict):
        errors.append(f"{where}: 'contact' must be a mapping")
        return slack, oncall
    for key in value:
        if key not in _CONTACT_KEYS:
            errors.append(f"{where}: unknown contact field '{key}'")
    if "slack" in value:
        raw = value["slack"]
        if raw is False or (isinstance(raw, str) and raw.startswith("#")):
            slack = raw
        else:
            errors.append(f"{where}: 'contact.slack' must be a string starting with '#' or false")
    if "oncall" in value:
        raw = value["oncall"]
        if isinstance(raw, str):
            oncall = raw
        else:
            errors.append(f"{where}: 'contact.oncall' must be a string")
    return slack, oncall


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


def _parse_rule(raw: object, index: int, errors: list[str]) -> OwnersRule | None:
    where = f"rules[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}: each rule must be a mapping")
        return None
    for key in raw:
        if key not in _RULE_KEYS:
            errors.append(f"{where}: unknown field '{key}'")
    match = raw.get("match")
    if not isinstance(match, str) or not match:
        errors.append(f"{where}: 'match' is required and must be a non-empty string")
        return None

    rule = OwnersRule(match=match)
    if "owners" in raw:
        rule.owners = _validate_owners_value(raw["owners"], where, errors)
    if "contact" in raw:
        rule.slack, rule.oncall = _validate_contact(raw["contact"], where, errors)
    if "status" in raw:
        rule.status = _validate_status(raw["status"], where, errors)
    if "inherit" in raw:
        rule.inherit = _validate_inherit(raw["inherit"], where, errors)
    return rule


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
        errors.append("'owners' is required (a list of strings, or null for unowned-by-design)")
        owners: list[str] | None = []
    else:
        validated = _validate_owners_value(data["owners"], "owners", errors)
        owners = [] if isinstance(validated, _Unset) else validated

    file = OwnersFile(path=path, directory=directory, owners=owners)

    if "contact" in data:
        file.slack, file.oncall = _validate_contact(data["contact"], "contact", errors)
    if "status" in data:
        file.status = _validate_status(data["status"], "status", errors)
    if "inherit" in data:
        inherit = _validate_inherit(data["inherit"], "inherit", errors)
        file.inherit = True if isinstance(inherit, _Unset) else inherit

    if "rules" in data:
        raw_rules = data["rules"]
        if not isinstance(raw_rules, list):
            errors.append("'rules' must be a list")
        else:
            for i, raw_rule in enumerate(raw_rules):
                rule = _parse_rule(raw_rule, i, errors)
                if rule is not None:
                    file.rules.append(rule)

    # A missing version or owners makes the file unusable for resolution.
    if data.get("version") != 1 or "owners" not in data:
        return None, errors
    return file, errors


def normalize_product_owners(owners: list[str]) -> list[str]:
    """Apply the ``product.yaml`` alias rule: keep ``@handles`` and team slugs, but
    a list consisting only of the ``team-CHANGEME`` scaffold placeholder is empty."""
    if all(o == CHANGEME_SLUG for o in owners):
        return []
    return [o for o in owners if o != CHANGEME_SLUG]


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
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        return None
    owners = normalize_product_owners(raw)
    return OwnersFile(path=path, directory=directory, owners=owners, is_alias=True)
