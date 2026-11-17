"""Proof rules for the SDK upgrader's bump of a first-party Python SDK.

The upgrader opens a pull request minutes after each SDK release, so the release age that holds
third-party updates back cannot apply. The bump is held to a narrow shape instead: only the
version of a first-party package moves, in manifests and lockfiles alike, and PyPI must serve
exactly the files the lockfiles name, each with a provenance attestation from the SDK's release
workflow. A release that changes the package's core requirements or its Python range goes to a
person, because the lockfiles would then need more than a version change.
"""

from __future__ import annotations

import re
import copy
import json
import base64
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from change_prover.core.policy import PLAIN_VERSION, Refused, check_bump

FIRST_PARTY = ("posthoganalytics", "posthog")
REGISTRY = "https://pypi.org/simple"
PUBLISHER = {"kind": "GitHub", "repository": "PostHog/posthog-python", "workflow": "release.yml"}
LOCKFILE_NAME = "uv.lock"
# One first-party requirement in a manifest line, such as `"posthoganalytics==7.91.1",` or `posthog>=7.91.1`.
SPEC = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<name>posthoganalytics|posthog)(?P<operator>==|>=|~=)"
    rf"(?P<version>{PLAIN_VERSION.pattern})(?![A-Za-z0-9_.])"
)
# The fields of a first-party lockfile package that follow the release. Every other field must stay.
RELEASE_FIELDS = ("version", "sdist", "wheels")
EXTRA_MARKER = re.compile(r"\bextra\s*==")
# The versions one side of a lockfile names, keyed by the package name and whether its entry or a specifier names it.
Named = dict[tuple[str, str], str]


@dataclass(frozen=True, kw_only=True)
class Move:
    """A first-party package's version before and after the bump."""

    old: str
    new: str


@dataclass(frozen=True, kw_only=True)
class FileMoves:
    """The first-party moves in one changed file, and its new first-party entries when it is a lockfile."""

    moves: dict[str, Move]
    entries: dict[str, dict[str, Any]]


def release_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def add_move(moves: dict[str, Move], where: str, name: str, old: str, new: str) -> None:
    """Adds a move of ``name``. Every move of one name must reach one version.

    The newest version any file moves from is kept, because that is the release the lockfile held,
    and a requirements file with a lagging floor says nothing about what was installed.
    """
    check_bump(f"{where} {name}", old, new)
    previous = moves.get(name)
    if previous is not None and previous.new != new:
        raise Refused(f"{where} moves {name} to more than one version")
    if previous is None or release_key(old) > release_key(previous.old):
        moves[name] = Move(old=old, new=new)


def check_manifest(path: str, base: bytes, head: bytes) -> dict[str, Move]:
    """The first-party moves in a pyproject.toml or requirements file whose only changes are their versions."""
    base_lines, head_lines = base.split(b"\n"), head.split(b"\n")
    if len(base_lines) != len(head_lines):
        raise Refused(f"{path} adds or removes lines")
    moves: dict[str, Move] = {}
    for before, after in zip(base_lines, head_lines):
        if before == after:
            continue
        try:
            old_line, new_line = before.decode("utf-8"), after.decode("utf-8")
        except UnicodeDecodeError as error:
            raise Refused(f"{path} is not UTF-8") from error
        old_specs, new_specs = list(SPEC.finditer(old_line)), list(SPEC.finditer(new_line))
        if len(old_specs) != 1 or len(new_specs) != 1:
            raise Refused(f"{path} changes a line that is not one first-party requirement")
        old_spec, new_spec = old_specs[0], new_specs[0]
        old_rest = old_line[: old_spec.start("version")], old_line[old_spec.end("version") :]
        new_rest = new_line[: new_spec.start("version")], new_line[new_spec.end("version") :]
        if old_rest != new_rest:
            raise Refused(f"{path} changes more than a version")
        add_move(moves, path, old_spec["name"], old_spec["version"], new_spec["version"])
    if not moves:
        raise Refused(f"{path} changes no first-party version")
    return moves


def load_lock(path: str, text: bytes) -> dict[str, Any]:
    """A uv.lock as uv reads it. TOML refuses a repeated key, so two readers cannot disagree on one."""
    try:
        return tomllib.loads(text.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise Refused(f"{path} does not parse") from error


def first_party_entry(path: str, lock: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """The registry package of a first-party name. A workspace project of that name is not the SDK."""
    entries = [
        entry
        for entry in lock.get("package", [])
        if isinstance(entry, dict) and entry.get("name") == name and "registry" in (entry.get("source") or {})
    ]
    if len(entries) > 1:
        raise Refused(f"{path} locks {name} more than once")
    return entries[0] if entries else None


def record(named: Named, path: str, key: tuple[str, str], version: str) -> None:
    if named.setdefault(key, version) != version:
        raise Refused(f"{path} names {key[0]} at more than one version")


def strip_specifier(path: str, requirement: dict[str, Any], named: Named) -> None:
    specifier = requirement.get("specifier")
    match = re.fullmatch(rf"(==|>=|~=)({PLAIN_VERSION.pattern})", specifier) if isinstance(specifier, str) else None
    if match is None:
        raise Refused(f"{path} gives {requirement.get('name')} a specifier this proof does not read")
    requirement["specifier"] = match[1]
    record(named, path, (requirement["name"], "specifier"), match[2])


def without_release(path: str, lock: dict[str, Any], named: Named) -> Any:
    """The lockfile with the fields a first-party release may change taken out and recorded in ``named``.

    The remaining structure must match between the merge base and the head exactly.
    """
    stripped = copy.deepcopy(lock)
    for entry in stripped.get("package", []):
        if not isinstance(entry, dict):
            continue
        source = entry.get("source") or {}
        if entry.get("name") in FIRST_PARTY and "registry" in source:
            if source != {"registry": REGISTRY}:
                raise Refused(f"{path} locks {entry['name']} from a registry other than PyPI")
            version = entry.get("version")
            if not isinstance(version, str):
                raise Refused(f"{path} locks {entry['name']} without a version")
            record(named, path, (entry["name"], "package"), version)
            for field in RELEASE_FIELDS:
                entry.pop(field, None)
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            continue
        groups = [metadata.get("requires-dist") or [], *((metadata.get("requires-dev") or {}).values())]
        for requirements in groups:
            for requirement in requirements:
                if isinstance(requirement, dict) and requirement.get("name") in FIRST_PARTY:
                    strip_specifier(path, requirement, named)
    return stripped


def check_lock(path: str, base: bytes, head: bytes) -> FileMoves:
    """The first-party moves in a uv.lock whose only changes follow them, and the new first-party entries."""
    base_lock, head_lock = load_lock(path, base), load_lock(path, head)
    old_named: Named = {}
    new_named: Named = {}
    if without_release(path, base_lock, old_named) != without_release(path, head_lock, new_named):
        raise Refused(f"{path} changes more than the first-party versions")
    for name in FIRST_PARTY:
        # An entry whose version stays keeps its files, because only a moved release is checked against PyPI.
        before, after = first_party_entry(path, base_lock, name), first_party_entry(path, head_lock, name)
        if before is not None and after is not None and before["version"] == after["version"] and before != after:
            raise Refused(f"{path} changes the files of {name} without moving its version")
    released: dict[str, Move] = {}
    # Equal stripped trees name the same keys on both sides.
    for key, old in old_named.items():
        if old != new_named[key]:
            add_move(released, path, key[0], old, new_named[key])
    if not released:
        raise Refused(f"{path} changes no first-party version")
    entries = {name: entry for name in released if (entry := first_party_entry(path, head_lock, name)) is not None}
    return FileMoves(moves=released, entries=entries)


def lock_files(path: str, entry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The files a lockfile entry names, keyed by file name, with the hash, size and URL it pins."""
    artifacts = [*([entry["sdist"]] if "sdist" in entry else []), *entry.get("wheels", [])]
    files: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        url = artifact.get("url") if isinstance(artifact, dict) else None
        if not isinstance(url, str) or not url.startswith("https://files.pythonhosted.org/"):
            raise Refused(f"{path} names a {entry['name']} file outside PyPI's file host")
        name = url.rpartition("/")[2]
        if name in files:
            raise Refused(f"{path} names {name} twice")
        files[name] = artifact
    if not files:
        raise Refused(f"{path} names no file for {entry['name']}")
    return files


def core_requirements(release: Mapping[str, Any]) -> list[str]:
    """The release's requirements that apply without an extra, the ones its lockfile entry depends on."""
    return sorted(
        requirement
        for requirement in release["info"].get("requires_dist") or []
        if not EXTRA_MARKER.search(requirement)
    )


def require_document(path: str, document: Any | None) -> Any:
    """A PyPI JSON document. A missing one is refused, because the proof cannot read it."""
    if document is None:
        raise Refused(f"PyPI has no {path}")
    return document


def check_file(path: str, base: bytes, head: bytes) -> FileMoves:
    if path.rpartition("/")[2] == LOCKFILE_NAME:
        return check_lock(path, base, head)
    return FileMoves(moves=check_manifest(path, base, head), entries={})


def check_one_version(moves: Mapping[str, Move]) -> None:
    """The SDK publishes posthoganalytics and posthog from one release, so both move to one version."""
    if len({move.new for move in moves.values()}) > 1:
        raise Refused("the pull request moves the first-party packages to different versions")


def check_release(
    name: str,
    new: str,
    locked: list[tuple[str, Mapping[str, Any]]],
    release: Mapping[str, Any],
    old_release: Mapping[str, Any] | None,
) -> dict[str, str]:
    """PyPI serves exactly the locked files of ``name`` at ``new``. Returns each served file's sha256.

    ``old_release`` is the release the lockfiles held, or None when no lockfile holds ``name``.
    A lockfile holds the old release's requirements, and a package no lockfile holds has none to go stale.
    """
    if old_release is not None:
        if core_requirements(release) != core_requirements(old_release):
            raise Refused(f"{name} {new} changes its requirements")
        if release["info"].get("requires_python") != old_release["info"].get("requires_python"):
            raise Refused(f"{name} {new} changes the Python versions it supports")
    served = {item["filename"]: item for item in release["urls"]}
    if not served:
        raise Refused(f"PyPI serves no file for {name} {new}")
    for item in served.values():
        if item.get("yanked"):
            raise Refused(f"{item['filename']} is yanked")
    for path, entry in locked:
        files = lock_files(path, entry)
        if set(files) != set(served):
            raise Refused(f"{path} does not name every file PyPI serves for {name} {new}")
        for filename, artifact in files.items():
            item = served[filename]
            if artifact.get("hash") != f"sha256:{item['digests']['sha256']}":
                raise Refused(f"{path} pins a hash for {filename} that PyPI does not serve")
            if artifact.get("size") != item["size"] or artifact.get("url") != item["url"]:
                raise Refused(f"{path} pins a size or URL for {filename} that PyPI does not serve")
    return {filename: item["digests"]["sha256"] for filename, item in served.items()}


def check_provenance(filename: str, sha256: str, provenance: Mapping[str, Any]) -> None:
    """Every attestation for the file comes from the SDK's release workflow and names this file and hash.

    PyPI verified each attestation's signature when it accepted the upload. This check reads the
    publisher and the signed statement, and does not verify the signature again.
    """
    bundles = provenance.get("attestation_bundles") or []
    if not bundles:
        raise Refused(f"{filename} has no provenance")
    for bundle in bundles:
        publisher = bundle.get("publisher") or {}
        if {key: publisher.get(key) for key in PUBLISHER} != PUBLISHER:
            raise Refused(f"{filename} was not published by {PUBLISHER['repository']} {PUBLISHER['workflow']}")
        attestations = bundle.get("attestations") or []
        if not attestations:
            raise Refused(f"{filename} has an empty attestation bundle")
        for attestation in attestations:
            try:
                statement = json.loads(base64.b64decode(attestation["envelope"]["statement"], validate=True))
            except (KeyError, TypeError, ValueError) as error:
                raise Refused(f"{filename} has an attestation this proof does not read") from error
            if statement.get("subject") != [{"name": filename, "digest": {"sha256": sha256}}]:
                raise Refused(f"{filename} has an attestation for another file")
