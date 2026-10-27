"""Deterministic verification of a Renovate dependency-update pull request.

Stamphog never treats a lockfile as harmless, because a lockfile selects the third-party code that
gets installed. A Renovate PR changes little besides lockfiles, so before stamphog lets its reviewer
judge one, this module proves what the lockfiles install, against facts that the PR cannot forge:

- GitHub attests the author, the head branch and the PR's one commit.
- The manifests change only the version specifiers of dependencies that they already declare, and
  a lockfile locks a new version of each one.
- Every version change is a minor or patch update, and never a minor update below 1.0. The same
  holds for every changed reference to a locked version, so a dependent cannot move to another
  major line that the lockfile already held.
- The lockfiles add no package that they did not already lock, keep the entry of every version that
  stays, never point a dependency at another package, and resolve every new version from the
  public registry.
- The registry attests that each new version is at least ``MINIMUM_RELEASE_AGE`` old and that its
  hashes and download URLs match the lockfile.
- Measured against every version of the package that the base locked, each new version keeps the
  provenance that any of them had, adds no install script that one of them did not have, and keeps
  a wheel for every platform family that one of them had a wheel for.

Every check fails closed. A problem is one sentence that names the file or the package, and the
result is verified only when no problem was found and at least one version changed.
"""

from __future__ import annotations

import re
import json
import tomllib
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion

from posthog.dataclasses import frozen
from posthog.egress.npm_registry import npm_packument_url, npm_registry_request
from posthog.egress.pypi import pypi_provenance_url, pypi_release_url, pypi_request

RENOVATE_BOT_USER_ID = 29139614
RENOVATE_BOT_LOGIN = "renovate[bot]"
RENOVATE_HEAD_PREFIX = "renovate/"
# GitHub commits as web-flow when an App commits through the API, and signs the commit itself.
GITHUB_WEB_FLOW_LOGIN = "web-flow"

# Matches minimumReleaseAge in .github/renovate.json5 and the pnpm and uv cooldowns.
MINIMUM_RELEASE_AGE = timedelta(days=7)
# Bounds the registry reads for one PR. A larger update fails closed rather than slowing the run.
MAX_VERSION_CHANGES = 100
# PyPI attests provenance per file, and one release can ship dozens of wheels.
MAX_DISTRIBUTION_FILES = 1000

PNPM_LOCKFILE = "pnpm-lock.yaml"
UV_LOCKFILE = "uv.lock"
_MANIFESTS = frozenset({"package.json", "pnpm-workspace.yaml", "pyproject.toml"})
_LOCKFILES = frozenset({PNPM_LOCKFILE, UV_LOCKFILE})

_PYPI_REGISTRY = "https://pypi.org/simple"
_NPM_DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
_NPM_INSTALL_SCRIPTS = ("preinstall", "install", "postinstall")
# Ranges only. A protocol (npm:, file:, git+, workspace:) or a URL redirects the install elsewhere.
_NPM_RANGE_RE = re.compile(r"^[0-9A-Za-z.^~<>=*|+\s-]+$")
# Package names and versions reach the reviewer's trusted prompt block, so they must not carry text.
_NPM_NAME_RE = re.compile(r"^(@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*$")
_PYPI_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_PREFIX_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)")
_PYPI_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.(whl|tar\.gz|zip)$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]*$")
# uv rewrites these when the resolution changes, so they may differ without a version change.
_UV_LOCK_DERIVED_KEYS = frozenset({"package", "revision", "resolution-markers"})
_UV_EDGE_TABLES = ("dependencies", "optional-dependencies", "dev-dependencies")
# A package that keeps its version may still change these. uv rewrites its edges when a dependency's
# version changes, and its metadata when a manifest changes. uv sync --frozen installs from the
# edges, so the edges are checked one by one.
_UV_RETAINED_DERIVED_KEYS = frozenset({*_UV_EDGE_TABLES, "metadata", "resolution-markers"})
_WHEEL_PLATFORM_FAMILIES = {
    "manylinux": "linux",
    "musllinux": "linux",
    "linux": "linux",
    "macosx": "macos",
    "win": "windows",
}
_ALL_WHEEL_PLATFORMS = frozenset(_WHEEL_PLATFORM_FAMILIES.values())
_PNPM_LOCK_DERIVED_KEYS = frozenset({"packages", "snapshots", "importers", "catalogs"})

_REGISTRY_TIMEOUT_SECONDS = 20
_REGISTRY_WORKERS = 8
_REGISTRY_SOURCE = "stamphog_renovate"
# A full npm packument holds every version's manifest. A large package's packument takes hundreds of
# MB once parsed, so the worker process parses only a few at a time.
_NPM_PACKUMENT_SLOTS = threading.BoundedSemaphore(2)

Ecosystem = Literal["npm", "pypi"]
ReadFile = Callable[[str, str], str | None]


@frozen
class VersionChange:
    ecosystem: Ecosystem
    name: str
    old_version: str
    new_version: str


@frozen
class RenovateVerification:
    problems: tuple[str, ...]
    changes: tuple[VersionChange, ...] = ()
    # The lockfiles the checks above cover, so the engine may take them out of the deny-list.
    cleared_paths: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return not self.problems and bool(self.changes)

    def to_context(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "problems": list(self.problems),
            "changes": [
                {
                    "ecosystem": change.ecosystem,
                    "name": change.name,
                    "old_version": change.old_version,
                    "new_version": change.new_version,
                }
                for change in self.changes
            ],
            "cleared_paths": list(self.cleared_paths),
            "minimum_release_age_days": MINIMUM_RELEASE_AGE.days,
        }


@frozen
class _NpmLockedVersion:
    change: VersionChange
    integrity: str
    base_versions: tuple[str, ...]


@frozen
class _LockedFile:
    url: str
    hash: str

    @property
    def filename(self) -> str:
        return PurePosixPath(self.url).name


@frozen
class _BaseRelease:
    version: str
    filenames: tuple[str, ...]


@frozen
class _UvLockedVersion:
    change: VersionChange
    new_files: tuple[_LockedFile, ...]
    base_releases: tuple[_BaseRelease, ...]


@frozen
class RegistryReaders:
    """The registry reads, injectable so the checks run without network in tests."""

    npm_packument: Callable[[str], dict[str, Any] | None]
    pypi_release: Callable[[str, str], dict[str, Any] | None]
    pypi_has_provenance: Callable[[str, str, str], bool]


def is_renovate_pr(pr: Mapping[str, Any], repo: str) -> bool:
    """Whether GitHub attests this PR as Renovate's, from the webhook or API payload alone.

    The numeric user id is the anchor: an App's bot login cannot be registered by anyone else, and
    the id survives a rename. The head must live in the base repo, because a fork's branch name is
    whatever the fork's owner chose.
    """
    user = pr.get("user") or {}
    if user.get("type") != "Bot" or user.get("id") != RENOVATE_BOT_USER_ID:
        return False
    if (user.get("login") or "") != RENOVATE_BOT_LOGIN:
        return False
    head = pr.get("head") or {}
    head_repo = ((head.get("repo") or {}).get("full_name") or "").lower()
    return head_repo == repo.lower() and str(head.get("ref") or "").startswith(RENOVATE_HEAD_PREFIX)


def commit_problems(commits: list[dict[str, Any]], head_sha: str) -> list[str]:
    """The PR must be one commit, the reviewed head, authored by Renovate and committed and signed by GitHub.

    Renovate rebuilds its branch as a single new commit on the base branch every time it updates
    it, so a second commit came from somebody else. The commit author alone proves little, because
    GitHub maps it from an email address that any committer can set.
    """
    if len(commits) != 1:
        return ["The PR is not exactly one commit, so someone other than Renovate added to it."]
    commit = commits[0]
    if commit.get("sha") != head_sha:
        return ["The PR's commit is not the reviewed head."]
    author = commit.get("author") or {}
    committer = commit.get("committer") or {}
    verification = (commit.get("commit") or {}).get("verification") or {}
    if author.get("id") != RENOVATE_BOT_USER_ID:
        return [f"The commit is not authored by {RENOVATE_BOT_LOGIN}."]
    if committer.get("login") != GITHUB_WEB_FLOW_LOGIN or verification.get("verified") is not True:
        return ["The commit is not committed and signed by GitHub."]
    return []


def changed_file_problems(files: list[dict[str, Any]]) -> list[str]:
    problems = []
    for file in files:
        path = str(file.get("filename") or "")
        name = PurePosixPath(path).name
        if name not in _MANIFESTS | _LOCKFILES:
            problems.append(f"{path} is not a dependency manifest or lockfile.")
        elif file.get("status") != "modified":
            problems.append(f"{path} is {file.get('status') or 'changed'}, not modified in place.")
    if not problems and not any(PurePosixPath(str(f.get("filename") or "")).name in _LOCKFILES for f in files):
        problems.append("The PR changes no pnpm-lock.yaml or uv.lock.")
    return problems


def _without(document: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    excluded = set(keys)
    return {key: value for key, value in document.items() if key not in excluded}


def _npm_range_map_problems(path: str, field: str, base: Any, head: Any) -> list[str]:
    if not isinstance(base, dict) or not isinstance(head, dict):
        return [f"{path} changes the shape of {field}."]
    if set(base) != set(head):
        return [f"{path} adds or removes an entry in {field}."]
    return [
        f"{path} sets {field}.{name} to something other than a version range."
        for name, value in head.items()
        if value != base[name] and not (isinstance(value, str) and _NPM_RANGE_RE.match(value))
    ]


def package_json_problems(path: str, base_text: str, head_text: str) -> list[str]:
    base, head = json.loads(base_text), json.loads(head_text)
    if not isinstance(base, dict) or not isinstance(head, dict):
        return [f"{path} is not a JSON object."]
    if _without(base, _NPM_DEPENDENCY_FIELDS) != _without(head, _NPM_DEPENDENCY_FIELDS):
        return [f"{path} changes fields other than dependency versions."]
    problems = []
    for field in _NPM_DEPENDENCY_FIELDS:
        if field in base or field in head:
            problems.extend(_npm_range_map_problems(path, field, base.get(field, {}), head.get(field, {})))
    return problems


def pnpm_workspace_problems(path: str, base_text: str, head_text: str) -> list[str]:
    base, head = yaml.safe_load(base_text) or {}, yaml.safe_load(head_text) or {}
    if not isinstance(base, dict) or not isinstance(head, dict):
        return [f"{path} is not a YAML mapping."]
    if _without(base, ("catalog", "catalogs")) != _without(head, ("catalog", "catalogs")):
        return [f"{path} changes settings other than catalog versions."]
    problems = []
    if "catalog" in base or "catalog" in head:
        problems.extend(_npm_range_map_problems(path, "catalog", base.get("catalog", {}), head.get("catalog", {})))
    base_catalogs, head_catalogs = base.get("catalogs", {}), head.get("catalogs", {})
    if not isinstance(base_catalogs, dict) or not isinstance(head_catalogs, dict):
        return [*problems, f"{path} changes the shape of catalogs."]
    if set(base_catalogs) != set(head_catalogs):
        return [*problems, f"{path} adds or removes a catalog."]
    for name in base_catalogs:
        problems.extend(_npm_range_map_problems(path, f"catalogs.{name}", base_catalogs[name], head_catalogs[name]))
    return problems


def _requirement_problem(path: str, base: Any, head: Any) -> str | None:
    if base == head:
        return None
    if not isinstance(base, str) or not isinstance(head, str):
        return f"{path} changes a non-string dependency entry."
    try:
        old, new = Requirement(base), Requirement(head)
    except InvalidRequirement:
        return f"{path} has a dependency entry that does not parse."
    if (old.name, old.extras, str(old.marker), old.url) != (new.name, new.extras, str(new.marker), new.url):
        return f"{path} changes {old.name} beyond its version specifier."
    if new.url is not None:
        return f"{path} pins {new.name} to a direct URL."
    return None


def _requirement_list_problems(path: str, base: Any, head: Any) -> list[str]:
    if not isinstance(base, list) or not isinstance(head, list) or len(base) != len(head):
        return [f"{path} adds or removes a dependency."]
    return [problem for old, new in zip(base, head) if (problem := _requirement_problem(path, old, new))]


def _requirement_table_problems(path: str, base: Any, head: Any) -> list[str]:
    if not isinstance(base, dict) or not isinstance(head, dict) or set(base) != set(head):
        return [f"{path} adds or removes a dependency group."]
    return [problem for name in base for problem in _requirement_list_problems(path, base[name], head[name])]


def pyproject_problems(path: str, base_text: str, head_text: str) -> list[str]:
    base, head = tomllib.loads(base_text), tomllib.loads(head_text)
    base_project, head_project = base.get("project", {}), head.get("project", {})
    dependency_keys = ("dependencies", "optional-dependencies")
    if _without(base, ("project", "dependency-groups")) != _without(head, ("project", "dependency-groups")):
        return [f"{path} changes settings other than dependency versions."]
    if _without(base_project, dependency_keys) != _without(head_project, dependency_keys):
        return [f"{path} changes project fields other than dependency versions."]
    return [
        *_requirement_list_problems(path, base_project.get("dependencies", []), head_project.get("dependencies", [])),
        *_requirement_table_problems(
            path, base_project.get("optional-dependencies", {}), head_project.get("optional-dependencies", {})
        ),
        *_requirement_table_problems(path, base.get("dependency-groups", {}), head.get("dependency-groups", {})),
    ]


def _release_line(version: str) -> tuple[int, ...] | None:
    """The versions that ``is_major_update`` treats as compatible: one major, or one minor below 1.0."""
    match = _VERSION_PREFIX_RE.match(version)
    if match is None:
        return None
    major = int(match["major"])
    return (major,) if major else (0, int(match["minor"]))


def is_major_update(change: VersionChange) -> bool:
    """Whether a change may break callers: a new major, or a new minor below 1.0.

    It matches the updates Renovate automerges here, which are minor and patch updates except 0.x
    minors. A version that does not start with two numbers counts as major.
    """
    old, new = _VERSION_PREFIX_RE.match(change.old_version), _VERSION_PREFIX_RE.match(change.new_version)
    if old is None or new is None:
        return True
    old_major, new_major = int(old["major"]), int(new["major"])
    return old_major != new_major or (new_major == 0 and old["minor"] != new["minor"])


def _replaced_version(base_versions: list[str], *, kept: set[str], new_version: str) -> str:
    """The base version a new one replaces: one the head no longer locks, else any base version.

    A lockfile can hold several versions of one package, so a new version only replaces one of
    them when the head drops it. Otherwise the new version sits beside the old ones. Among the
    candidates, one in the new version's release line is the one the major-update check compares
    against, so two updates in one lockfile pair up by line and not by lockfile order.
    """
    candidates = [version for version in base_versions if version not in kept] or base_versions
    new_line = _release_line(new_version)
    same_line = [version for version in candidates if new_line is not None and _release_line(version) == new_line]
    return (same_line or candidates)[-1]


def _split_pnpm_key(key: str) -> tuple[str, str] | None:
    name, separator, version = key.rpartition("@")
    if not separator or not _NPM_NAME_RE.match(name) or not _VERSION_RE.match(version):
        return None
    return name, version


def pnpm_lock_versions(path: str, base_text: str, head_text: str) -> tuple[list[_NpmLockedVersion], list[str]]:
    base = yaml.load(base_text, Loader=yaml.CSafeLoader) or {}
    head = yaml.load(head_text, Loader=yaml.CSafeLoader) or {}
    if base.get("lockfileVersion") != head.get("lockfileVersion"):
        return [], [f"{path} changes the lockfile version."]
    if _without(base, _PNPM_LOCK_DERIVED_KEYS) != _without(head, _PNPM_LOCK_DERIVED_KEYS):
        return [], [f"{path} changes lockfile settings, overrides or patches."]
    base_packages: dict[str, Any] = base.get("packages") or {}
    head_packages: dict[str, Any] = head.get("packages") or {}
    base_versions: dict[str, list[str]] = {}
    for key in base_packages:
        if (parsed := _split_pnpm_key(key)) is not None:
            base_versions.setdefault(parsed[0], []).append(parsed[1])

    locked: list[_NpmLockedVersion] = []
    problems: list[str] = []
    for key, entry in head_packages.items():
        if key in base_packages:
            if (entry or {}).get("resolution") != (base_packages[key] or {}).get("resolution"):
                problems.append(f"{path} changes the resolution of {key} without changing its version.")
            continue
        parsed = _split_pnpm_key(key)
        if parsed is None:
            problems.append(f"{path} locks an entry that is not a plain registry package.")
            continue
        name, version = parsed
        if name not in base_versions:
            problems.append(f"{path} adds {name}, which it did not lock before.")
            continue
        resolution = (entry or {}).get("resolution") or {}
        if set(resolution) != {"integrity"}:
            problems.append(f"{path} resolves {name}@{version} from somewhere other than the registry.")
            continue
        locked.append(
            _NpmLockedVersion(
                change=VersionChange(
                    ecosystem="npm",
                    name=name,
                    old_version=_replaced_version(
                        base_versions[name],
                        kept={v for v in base_versions[name] if f"{name}@{v}" in head_packages},
                        new_version=version,
                    ),
                    new_version=version,
                ),
                integrity=str(resolution["integrity"]),
                base_versions=tuple(base_versions[name]),
            )
        )
    return locked, [*problems, *_pnpm_reference_problems(path, base, head)]


def _pnpm_reference_target(name: str, reference: Any, *, alias: bool) -> tuple[str, str] | None:
    """The package and version that a lockfile reference to ``name`` selects, or None.

    A reference is a version with an optional peer suffix, ``1.2.0(react@18.3.1)``. With ``alias``,
    it may also name another locked package, ``web-vitals@6.2.1``, which is how a published package
    that depends on ``npm:web-vitals@...`` is locked. Anything else is ``link:`` or ``file:``, which
    installs code the checks never saw.
    """
    if not isinstance(reference, str):
        return None
    target = reference.split("(", 1)[0]
    if alias and (parsed := _split_pnpm_key(target)) is not None:
        return parsed
    return (name, target) if _VERSION_RE.match(target) else None


def _pnpm_reference_problem(
    path: str,
    owner: str,
    name: str,
    base_reference: Any,
    reference: Any,
    packages: Mapping[str, Any],
    *,
    base_aliases: frozenset[tuple[str, str]] = frozenset(),
    alias: bool = False,
) -> str | None:
    """A changed reference must select a locked package, the same package as before, in the same release line.

    ``base_aliases`` holds the (dependency, package) aliases that the base locked. A published
    package declares its own aliases, so a new pair substitutes a package that no check has seen.
    """
    target = _pnpm_reference_target(name, reference, alias=alias)
    if target is None or f"{target[0]}@{target[1]}" not in packages:
        return f"{path} points {owner} at {name} through something other than a locked version."
    previous = _pnpm_reference_target(name, base_reference, alias=alias)
    if previous is None:
        if target[0] != name and (name, target[0]) not in base_aliases:
            return f"{path} points {owner} at another package for {name}."
        return None
    if previous[0] != target[0]:
        return f"{path} points {owner} at another package for {name}."
    change = VersionChange(ecosystem="npm", name=target[0], old_version=previous[1], new_version=target[1])
    if is_major_update(change):
        return f"{path} moves {owner} from {name} {previous[1]} to {target[1]}, a major update."
    return None


def _pnpm_specifier_map_problems(
    path: str, owner: str, base: Mapping[str, Any], head: Mapping[str, Any], packages: Mapping[str, Any]
) -> list[str]:
    if set(base) != set(head):
        return [f"{path} adds or removes a dependency of {owner}."]
    problems = []
    for name, entry in head.items():
        if entry == base[name]:
            continue
        if not isinstance(entry, dict) or set(entry) != {"specifier", "version"}:
            problems.append(f"{path} points {owner} at {name} through something other than a locked version.")
            continue
        base_reference = base[name].get("version") if isinstance(base[name], dict) else None
        if problem := _pnpm_reference_problem(path, owner, name, base_reference, entry["version"], packages):
            problems.append(problem)
    return problems


def _pnpm_snapshot_aliases(snapshots: Mapping[str, Any]) -> frozenset[tuple[str, str]]:
    return frozenset(
        (name, target[0])
        for snapshot in snapshots.values()
        for field in ("dependencies", "optionalDependencies")
        for name, reference in ((snapshot or {}).get(field) or {}).items()
        if (target := _pnpm_reference_target(name, reference, alias=True)) is not None and target[0] != name
    )


def _pnpm_reference_problems(path: str, base: Mapping[str, Any], head: Mapping[str, Any]) -> list[str]:
    """Every changed reference in ``importers``, ``catalogs`` and ``snapshots`` must select a locked package."""
    packages = head.get("packages") or {}
    base_importers, head_importers = base.get("importers") or {}, head.get("importers") or {}
    base_catalogs, head_catalogs = base.get("catalogs") or {}, head.get("catalogs") or {}
    if set(base_importers) != set(head_importers) or set(base_catalogs) != set(head_catalogs):
        return [f"{path} adds or removes a workspace package or a catalog."]
    problems = []
    for importer, head_entry in head_importers.items():
        base_entry, head_entry = base_importers[importer] or {}, head_entry or {}
        if _without(base_entry, _NPM_DEPENDENCY_FIELDS) != _without(head_entry, _NPM_DEPENDENCY_FIELDS):
            problems.append(f"{path} changes {importer} beyond its dependency versions.")
            continue
        for field in _NPM_DEPENDENCY_FIELDS:
            problems.extend(
                _pnpm_specifier_map_problems(
                    path, importer, base_entry.get(field) or {}, head_entry.get(field) or {}, packages
                )
            )
    for catalog, entries in head_catalogs.items():
        problems.extend(
            _pnpm_specifier_map_problems(
                path, f"catalog {catalog}", base_catalogs[catalog] or {}, entries or {}, packages
            )
        )

    base_snapshots = base.get("snapshots") or {}
    base_aliases = _pnpm_snapshot_aliases(base_snapshots)
    for key, snapshot in (head.get("snapshots") or {}).items():
        parsed = _split_pnpm_key(key.split("(", 1)[0])
        previous = base_snapshots.get(key)
        if previous is None:
            if parsed is None or f"{parsed[0]}@{parsed[1]}" not in packages:
                problems.append(f"{path} adds a snapshot that matches no locked package.")
                continue
            previous = {}
        owner = f"the snapshot of {parsed[0]}" if parsed is not None else "a snapshot"
        for field in ("dependencies", "optionalDependencies"):
            base_references = previous.get(field) or {}
            for name, reference in ((snapshot or {}).get(field) or {}).items():
                base_reference = base_references.get(name)
                if reference != base_reference and (
                    problem := _pnpm_reference_problem(
                        path, owner, name, base_reference, reference, packages, base_aliases=base_aliases, alias=True
                    )
                ):
                    problems.append(problem)
    return problems


def _uv_key(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    # One version can be locked from two indexes (torch from PyPI and from the PyTorch index).
    return str(entry.get("name")), str(entry.get("version")), json.dumps(entry.get("source"), sort_keys=True)


def _uv_files(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    files = [entry["sdist"]] if isinstance(entry.get("sdist"), dict) else []
    return [*files, *(wheel for wheel in entry.get("wheels") or [] if isinstance(wheel, dict))]


def _uv_filename(file: Mapping[str, Any]) -> str:
    return PurePosixPath(str(file.get("url") or "")).name


def _uv_edges(entry: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """A package's dependency edges, keyed by everything but the version and index they select."""
    edges: dict[str, Mapping[str, Any]] = {}
    for table in _UV_EDGE_TABLES:
        value = entry.get(table) or []
        groups = value.items() if isinstance(value, dict) else [("", value)]
        for group, group_edges in groups:
            for edge in group_edges:
                key = json.dumps([table, group, _without(edge, ("version", "source"))], sort_keys=True)
                edges[key] = edge
    return edges


def _uv_edge_version(edge: Mapping[str, Any], versions_by_name: Mapping[str, set[str]]) -> str | None:
    # uv names the version on an edge only when the lockfile holds more than one version of it.
    if "version" in edge:
        return str(edge["version"])
    versions = versions_by_name.get(str(edge.get("name")), set())
    return next(iter(versions)) if len(versions) == 1 else None


def _uv_retained_problems(
    path: str,
    previous: Mapping[str, Any],
    entry: Mapping[str, Any],
    base_versions: Mapping[str, set[str]],
    head_versions: Mapping[str, set[str]],
) -> list[str]:
    """A package that keeps its version keeps its files, and each dependency stays in its release line."""
    label = f"{entry.get('name')} {entry.get('version')}"
    if _without(entry, _UV_RETAINED_DERIVED_KEYS) != _without(previous, _UV_RETAINED_DERIVED_KEYS):
        return [f"{path} changes {label} without changing its version."]
    base_edges, head_edges = _uv_edges(previous), _uv_edges(entry)
    if set(base_edges) != set(head_edges):
        return [f"{path} changes the dependencies of {label} without changing its version."]
    problems = []
    for key, edge in head_edges.items():
        old, new = _uv_edge_version(base_edges[key], base_versions), _uv_edge_version(edge, head_versions)
        if old == new:
            continue
        dependency = str(edge.get("name"))
        if old is None or new is None or new not in head_versions.get(dependency, set()):
            problems.append(f"{path} points {label} at a {dependency} version that it does not lock.")
        elif is_major_update(VersionChange(ecosystem="pypi", name=dependency, old_version=old, new_version=new)):
            problems.append(f"{path} moves {label} from {dependency} {old} to {new}, a major update.")
    return problems


def uv_lock_versions(path: str, base_text: str, head_text: str) -> tuple[list[_UvLockedVersion], list[str]]:
    base, head = tomllib.loads(base_text), tomllib.loads(head_text)
    if _without(base, _UV_LOCK_DERIVED_KEYS) != _without(head, _UV_LOCK_DERIVED_KEYS):
        return [], [f"{path} changes lockfile options or manifest settings."]
    base_entries = {_uv_key(p): p for p in base.get("package", [])}
    base_by_name: dict[str, list[Mapping[str, Any]]] = {}
    base_versions_by_name: dict[str, set[str]] = {}
    for entry in base_entries.values():
        base_by_name.setdefault(str(entry.get("name")), []).append(entry)
        base_versions_by_name.setdefault(str(entry.get("name")), set()).add(str(entry.get("version")))
    head_versions_by_name: dict[str, set[str]] = {}
    for entry in head.get("package", []):
        head_versions_by_name.setdefault(str(entry.get("name")), set()).add(str(entry.get("version")))

    locked: list[_UvLockedVersion] = []
    problems: list[str] = []
    for entry in head.get("package", []):
        name, version = str(entry.get("name") or ""), str(entry.get("version") or "")
        previous = base_entries.get(_uv_key(entry))
        if previous is not None:
            problems.extend(_uv_retained_problems(path, previous, entry, base_versions_by_name, head_versions_by_name))
            continue
        if not _PYPI_NAME_RE.match(name) or not _VERSION_RE.match(version):
            problems.append(f"{path} locks an entry that is not a plain package name and version.")
            continue
        if name not in base_by_name:
            problems.append(f"{path} adds {name}, which it did not lock before.")
            continue
        if entry.get("source") != {"registry": _PYPI_REGISTRY}:
            problems.append(f"{path} resolves {name} {version} from somewhere other than PyPI.")
            continue
        base_versions = [str(p.get("version")) for p in base_by_name[name]]
        old_version = _replaced_version(
            base_versions, kept=set(base_versions) & head_versions_by_name[name], new_version=version
        )
        new_files = tuple(
            _LockedFile(url=str(file.get("url") or ""), hash=str(file.get("hash") or "")) for file in _uv_files(entry)
        )
        if not all(_PYPI_FILENAME_RE.match(file.filename) for file in new_files):
            problems.append(f"{path} locks a file of {name} {version} that is not a plain distribution name.")
            continue
        locked.append(
            _UvLockedVersion(
                change=VersionChange(ecosystem="pypi", name=name, old_version=old_version, new_version=version),
                new_files=new_files,
                base_releases=tuple(
                    _BaseRelease(
                        version=str(p.get("version")),
                        filenames=tuple(_uv_filename(file) for file in _uv_files(p)),
                    )
                    for p in base_by_name[name]
                ),
            )
        )
    return locked, problems


def _released_long_enough_ago(timestamp: Any, now: datetime) -> bool:
    try:
        released = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return False
    return released.tzinfo is not None and now - released >= MINIMUM_RELEASE_AGE


def _npm_installs_code(version: Mapping[str, Any]) -> bool:
    scripts = version.get("scripts") or {}
    return version.get("gypfile") is True or any(script in scripts for script in _NPM_INSTALL_SCRIPTS)


def npm_registry_problems(locked: _NpmLockedVersion, packument: dict[str, Any] | None, now: datetime) -> list[str]:
    change = locked.change
    label = f"{change.name}@{change.new_version}"
    if packument is None:
        return [f"The npm registry does not list {change.name}."]
    versions = packument.get("versions") or {}
    new = versions.get(change.new_version)
    if not isinstance(new, dict):
        return [f"The npm registry does not list {label}."]
    # A version the registry no longer lists counts as one with no provenance and no install script.
    base = [versions.get(version) or {} for version in locked.base_versions]
    problems = []
    if not _released_long_enough_ago((packument.get("time") or {}).get(change.new_version), now):
        problems.append(f"{label} was published less than {MINIMUM_RELEASE_AGE.days} days ago.")
    if (new.get("dist") or {}).get("integrity") != locked.integrity:
        problems.append(f"The lockfile hash for {label} does not match the npm registry.")
    if not (new.get("dist") or {}).get("attestations") and any(
        (version.get("dist") or {}).get("attestations") for version in base
    ):
        problems.append(f"{label} has no provenance attestation, and a version locked before had one.")
    if _npm_installs_code(new) and not all(_npm_installs_code(version) for version in base):
        problems.append(f"{label} adds an install script.")
    return problems


def _wheel_platforms(filenames: Iterable[str]) -> frozenset[str]:
    """The platform families that the wheels among these files install on without a build step."""
    platforms: set[str] = set()
    for filename in filenames:
        if not filename.endswith(".whl"):
            continue
        try:
            tags = parse_wheel_filename(filename)[3]
        except InvalidWheelFilename:
            continue
        for tag in tags:
            if tag.platform == "any":
                return _ALL_WHEEL_PLATFORMS
            platforms.update(
                family for prefix, family in _WHEEL_PLATFORM_FAMILIES.items() if tag.platform.startswith(prefix)
            )
    return frozenset(platforms)


def pypi_registry_problems(
    locked: _UvLockedVersion,
    release: dict[str, Any] | None,
    base_has_provenance: bool,
    new_has_provenance: bool,
    now: datetime,
) -> list[str]:
    """``base_has_provenance``: any file of any base version has it. ``new_has_provenance``: every new file has it."""
    change = locked.change
    label = f"{change.name} {change.new_version}"
    if release is None:
        return [f"PyPI does not list {label}."]
    if (release.get("info") or {}).get("yanked"):
        return [f"{label} is yanked on PyPI."]
    if not locked.new_files:
        return [f"The lockfile lists no files for {label}, so nothing proves its upload age or hash."]
    published = {str(file.get("filename")): file for file in release.get("urls") or [] if isinstance(file, dict)}
    problems = []
    for locked_file in locked.new_files:
        filename = locked_file.filename
        file = published.get(filename)
        if file is None:
            problems.append(f"PyPI does not list {filename} for {label}.")
            continue
        # uv downloads from the locked URL before it checks the hash, so a foreign host gets the request.
        if locked_file.url != file.get("url"):
            problems.append(f"The lockfile URL for {filename} is not the one PyPI lists.")
        if locked_file.hash != f"sha256:{(file.get('digests') or {}).get('sha256')}":
            problems.append(f"The lockfile hash for {filename} does not match PyPI.")
        if not _released_long_enough_ago(file.get("upload_time_iso_8601"), now):
            problems.append(f"{filename} was uploaded less than {MINIMUM_RELEASE_AGE.days} days ago.")
    base_platforms = _wheel_platforms(name for release in locked.base_releases for name in release.filenames)
    if lost := base_platforms - _wheel_platforms(file.filename for file in locked.new_files):
        problems.append(
            f"{label} ships no wheel for {', '.join(sorted(lost))}, so installing it there runs its build step."
        )
    if base_has_provenance and not new_has_provenance:
        problems.append(f"{label} has no provenance on every file, and a version locked before had it.")
    return problems


def _read_pair(read_file: ReadFile, path: str, base_sha: str, head_sha: str) -> tuple[str, str] | None:
    base_text, head_text = read_file(path, base_sha), read_file(path, head_sha)
    if base_text is None or head_text is None:
        return None
    return base_text, head_text


def _manifest_problems(path: str, base_text: str, head_text: str) -> list[str]:
    name = PurePosixPath(path).name
    if name == "package.json":
        return package_json_problems(path, base_text, head_text)
    if name == "pnpm-workspace.yaml":
        return pnpm_workspace_problems(path, base_text, head_text)
    return pyproject_problems(path, base_text, head_text)


def _changed_ranges(base: Mapping[str, Any], head: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {(name, str(value)) for name, value in head.items() if base.get(name) != value}


def _specifier_admits(specifier: str, version: str) -> bool:
    try:
        return SpecifierSet(specifier).contains(version, prereleases=True)
    except InvalidVersion:
        return False


def manifest_changed_specifiers(path: str, base_text: str, head_text: str) -> tuple[Ecosystem, set[tuple[str, str]]]:
    """Each (dependency, new specifier) that a manifest changes, for a manifest with no problems.

    The lockfile checks prove what gets installed, and CI installs with ``uv sync --frozen``, which
    never compares the lockfile with the manifest. So a specifier change that no locked version
    change matches would reach the next ``uv lock`` or ``pnpm install`` unchecked.
    """
    name = PurePosixPath(path).name
    if name == "package.json":
        base, head = json.loads(base_text), json.loads(head_text)
        maps = [(base.get(field, {}), head.get(field, {})) for field in _NPM_DEPENDENCY_FIELDS]
        return "npm", set().union(*(_changed_ranges(old, new) for old, new in maps))
    if name == "pnpm-workspace.yaml":
        base, head = yaml.safe_load(base_text) or {}, yaml.safe_load(head_text) or {}
        base_catalogs, head_catalogs = base.get("catalogs", {}), head.get("catalogs", {})
        maps = [
            (base.get("catalog", {}), head.get("catalog", {})),
            *((base_catalogs[catalog], head_catalogs[catalog]) for catalog in head_catalogs),
        ]
        return "npm", set().union(*(_changed_ranges(old, new) for old, new in maps))
    base, head = tomllib.loads(base_text), tomllib.loads(head_text)
    base_project, head_project = base.get("project", {}), head.get("project", {})
    lists = [
        (base_project.get("dependencies", []), head_project.get("dependencies", [])),
        *(
            (base_project["optional-dependencies"][extra], requirements)
            for extra, requirements in head_project.get("optional-dependencies", {}).items()
        ),
        *((base["dependency-groups"][group], entries) for group, entries in head.get("dependency-groups", {}).items()),
    ]
    requirements = [
        Requirement(new) for old_list, new_list in lists for old, new in zip(old_list, new_list) if old != new
    ]
    return "pypi", {(canonicalize_name(requirement.name), str(requirement.specifier)) for requirement in requirements}


def _registry_problems(
    npm_versions: list[_NpmLockedVersion],
    uv_versions: list[_UvLockedVersion],
    readers: RegistryReaders,
    now: datetime,
) -> list[str]:
    npm_by_name: dict[str, list[_NpmLockedVersion]] = {}
    for locked in npm_versions:
        npm_by_name.setdefault(locked.change.name, []).append(locked)

    def npm_problems(name: str, versions: list[_NpmLockedVersion]) -> list[str]:
        # Checking inside the slot drops the packument before the next one is parsed.
        with _NPM_PACKUMENT_SLOTS:
            packument = readers.npm_packument(name)
            return [problem for locked in versions for problem in npm_registry_problems(locked, packument, now)]

    def uv_problems(locked: _UvLockedVersion) -> list[str]:
        change = locked.change
        release = readers.pypi_release(change.name, change.new_version)
        new_provenance = bool(locked.new_files) and all(
            readers.pypi_has_provenance(change.name, change.new_version, file.filename) for file in locked.new_files
        )
        # The base versions' provenance matters only when a new file has none.
        base_provenance = not new_provenance and any(
            readers.pypi_has_provenance(change.name, base_release.version, filename)
            for base_release in locked.base_releases
            for filename in base_release.filenames
        )
        return pypi_registry_problems(locked, release, base_provenance, new_provenance, now)

    with ThreadPoolExecutor(max_workers=_REGISTRY_WORKERS, thread_name_prefix="stamphog-renovate") as executor:
        # PyPI jobs go first, so they do not queue behind npm jobs that wait for a packument slot.
        # Two lockfiles can lock the same version, so each one is read once.
        futures = [
            *(executor.submit(uv_problems, locked) for locked in dict.fromkeys(uv_versions)),
            *(executor.submit(npm_problems, name, versions) for name, versions in npm_by_name.items()),
        ]
        try:
            return [problem for future in futures for problem in future.result()]
        except BaseException:
            # Leaving the block waits for every queued read, so a registry outage would hold the
            # activity for each queued timeout before it retries.
            for future in futures:
                future.cancel()
            raise


def verify_renovate_update(
    *,
    pr: Mapping[str, Any],
    repo: str,
    commits: list[dict[str, Any]],
    files: list[dict[str, Any]],
    merge_base_sha: str,
    head_sha: str,
    read_file: ReadFile,
    now: datetime,
    readers: RegistryReaders | None = None,
) -> RenovateVerification:
    """Run every check and collect each problem. ``read_file`` returns a path's text at a commit, or None."""
    if not is_renovate_pr(pr, repo):
        return RenovateVerification(problems=("GitHub does not attest this PR as Renovate's.",))
    problems = [*commit_problems(commits, head_sha), *changed_file_problems(files)]
    if problems:
        return RenovateVerification(problems=tuple(problems))

    npm_versions: list[_NpmLockedVersion] = []
    uv_versions: list[_UvLockedVersion] = []
    cleared: list[str] = []
    respecified: list[tuple[str, Ecosystem, str, str]] = []
    for file in files:
        path = str(file["filename"])
        texts = _read_pair(read_file, path, merge_base_sha, head_sha)
        if texts is None:
            problems.append(f"{path} could not be read at both the merge base and the head.")
            continue
        try:
            name = PurePosixPath(path).name
            if name == PNPM_LOCKFILE:
                found, lock_problems = pnpm_lock_versions(path, *texts)
                npm_versions.extend(found)
            elif name == UV_LOCKFILE:
                found_uv, lock_problems = uv_lock_versions(path, *texts)
                uv_versions.extend(found_uv)
            else:
                manifest_problems = _manifest_problems(path, *texts)
                problems.extend(manifest_problems)
                if not manifest_problems:
                    ecosystem, specifiers = manifest_changed_specifiers(path, *texts)
                    respecified.extend((path, ecosystem, *specifier) for specifier in sorted(specifiers))
                continue
        except (ValueError, yaml.YAMLError, tomllib.TOMLDecodeError, TypeError, AttributeError):
            problems.append(f"{path} does not parse.")
            continue
        problems.extend(lock_problems)
        cleared.append(path)

    relocked: dict[tuple[Ecosystem, str], set[str]] = {}
    for npm_version in npm_versions:
        relocked.setdefault(("npm", npm_version.change.name), set()).add(npm_version.change.new_version)
    for uv_version in uv_versions:
        relocked.setdefault(("pypi", canonicalize_name(uv_version.change.name)), set()).add(
            uv_version.change.new_version
        )
    for path, ecosystem, dependency, specifier in respecified:
        new_versions = relocked.get((ecosystem, dependency))
        if new_versions is None:
            problems.append(f"{path} changes the specifier of {dependency}, and no lockfile locks a new version of it.")
        # pnpm refuses a frozen install whose lockfile specifiers differ from the manifests, and
        # uv sync --frozen does not compare them.
        elif ecosystem == "pypi" and not any(_specifier_admits(specifier, version) for version in new_versions):
            problems.append(f"{path} sets {dependency} to {specifier}, which no newly locked version meets.")
    # Two lockfiles can lock the same version, so both lists keep the first copy of each entry.
    changes = tuple(dict.fromkeys([*(v.change for v in npm_versions), *(v.change for v in uv_versions)]))
    problems.extend(
        f"{c.name} {c.old_version} -> {c.new_version} is a major update." for c in changes if is_major_update(c)
    )
    if len(npm_versions) + len(uv_versions) > MAX_VERSION_CHANGES:
        problems.append(f"The PR changes more than {MAX_VERSION_CHANGES} locked versions.")
    distribution_files = sum(
        len(v.new_files) + sum(len(release.filenames) for release in v.base_releases)
        for v in dict.fromkeys(uv_versions)
    )
    if distribution_files > MAX_DISTRIBUTION_FILES:
        problems.append(f"The PR's Python updates span more than {MAX_DISTRIBUTION_FILES} distribution files.")
    if not problems:
        problems.extend(_registry_problems(npm_versions, uv_versions, readers or default_registry_readers(), now))
    # A lockfile is cleared only by a verified result, so no consumer can clear one that a problem names.
    return RenovateVerification(
        problems=tuple(dict.fromkeys(problems)),
        changes=changes,
        cleared_paths=tuple(cleared) if changes and not problems else (),
    )


def _registry_json(response: Any) -> dict[str, Any] | None:
    """The registry's JSON body, or None when it has no such package or version.

    Any other error raises, so a rate limit or an outage retries the activity instead of refusing
    the update.
    """
    if response.status_code == 404:
        return None
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else None


def _read_npm_packument(name: str) -> dict[str, Any] | None:
    response = npm_registry_request(
        "GET",
        npm_packument_url(name),
        source=_REGISTRY_SOURCE,
        endpoint="packument",
        timeout=_REGISTRY_TIMEOUT_SECONDS,
    )
    return _registry_json(response)


def _read_pypi_release(name: str, version: str) -> dict[str, Any] | None:
    response = pypi_request(
        "GET",
        pypi_release_url(name, version),
        source=_REGISTRY_SOURCE,
        endpoint="release",
        timeout=_REGISTRY_TIMEOUT_SECONDS,
    )
    return _registry_json(response)


def _read_pypi_has_provenance(name: str, version: str, filename: str) -> bool:
    response = pypi_request(
        "GET",
        pypi_provenance_url(name, version, filename),
        source=_REGISTRY_SOURCE,
        endpoint="provenance",
        timeout=_REGISTRY_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True


def default_registry_readers() -> RegistryReaders:
    return RegistryReaders(
        npm_packument=_read_npm_packument,
        pypi_release=_read_pypi_release,
        pypi_has_provenance=_read_pypi_has_provenance,
    )
