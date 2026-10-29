"""Deterministic verification of a Renovate npm dependency-update pull request.

A lockfile selects the third-party code that gets installed, so before stamphog lets its reviewer
judge a Renovate PR, this module proves the shape of the update from facts the PR cannot forge:

- GitHub attests the author, the head branch and the PR's one commit.
- The manifests change only the version specifiers of dependencies that they already declare.
- Every changed specifier and every new locked version is a minor or patch update, and never a
  minor update below 1.0.
- The lockfile adds no package that it did not already lock, keeps every retained entry as it was,
  and resolves every new version from the registry by integrity hash alone.

The lockfile's dependency edges are pnpm's output on Renovate's commit, so this module does not
walk them. Whether each new version is safe to install is pnpm's check, so the lockfile's
`pnpm-workspace.yaml` must set `minimumReleaseAge` and `trustPolicy: no-downgrade`. Python updates
are out of scope: `uv sync --frozen` checks none of that, so they need a human. Every check fails closed.
"""

from __future__ import annotations

import re
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any

import yaml

from posthog.dataclasses import frozen

RENOVATE_BOT_USER_ID = 29139614
RENOVATE_BOT_LOGIN = "renovate[bot]"
RENOVATE_HEAD_PREFIX = "renovate/"
# GitHub commits as web-flow when an App commits through the API, and signs the commit itself.
GITHUB_WEB_FLOW_LOGIN = "web-flow"

PNPM_LOCKFILE = "pnpm-lock.yaml"
PNPM_WORKSPACE = "pnpm-workspace.yaml"
_MANIFESTS = frozenset({"package.json", PNPM_WORKSPACE})

_NPM_DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
# An exact, caret or tilde version, the forms Renovate writes. A protocol (npm:, file:, git+,
# workspace:) or a URL redirects the install elsewhere, and a dist-tag or an open range lets the next
# relock resolve any version, a new major included.
_NPM_RANGE_RE = re.compile(r"^[\^~]?\d+(\.\d+){0,2}(-[0-9A-Za-z.-]+)?$")
# Package names and versions reach the reviewer's trusted prompt block, so they must not carry text.
_NPM_NAME_RE = re.compile(r"^(@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*$")
_NUMERIC_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]*$")
_PNPM_LOCK_DERIVED_KEYS = frozenset({"packages", "snapshots", "importers", "catalogs"})
# Settings that skip the release-age, provenance or lockfile checks, or run every install script.
_PNPM_WEAKENING_SETTINGS = frozenset(
    {"dangerouslyAllowAllBuilds", "ignoreMissingTimeField", "trustLockfile", "trustPolicyIgnoreAfter"}
)
# The fields pnpm 9 writes on a registry package entry. Any other field, such as `version` or
# `dependencies`, overrides what the entry's key or its snapshot says.
_PNPM_REGISTRY_ENTRY_KEYS = frozenset(
    {
        "resolution",
        "engines",
        "peerDependencies",
        "peerDependenciesMeta",
        "hasBin",
        "cpu",
        "os",
        "libc",
        "deprecated",
        "bundledDependencies",
    }
)

ReadFile = Callable[[str, str], str | None]


@frozen
class VersionChange:
    name: str
    old_version: str
    new_version: str


@frozen
class LockedPackage:
    name: str
    version: str


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
        return asdict(self) | {"verified": self.verified}


def is_renovate_pr(pr: Mapping[str, Any], repo: str) -> bool:
    """Whether GitHub attests this PR as Renovate's. A fork's branch name is whatever its owner chose."""
    user = pr.get("user") or {}
    if user.get("type") != "Bot" or user.get("id") != RENOVATE_BOT_USER_ID or user.get("login") != RENOVATE_BOT_LOGIN:
        return False
    head = pr.get("head") or {}
    head_repo = ((head.get("repo") or {}).get("full_name") or "").lower()
    return head_repo == repo.lower() and str(head.get("ref") or "").startswith(RENOVATE_HEAD_PREFIX)


def commit_problems(commits: list[dict[str, Any]], head_sha: str) -> list[str]:
    """The PR must be one commit, the reviewed head, authored by Renovate and committed and signed by GitHub.

    Renovate rebuilds its branch as one new commit on every update, so a second commit came from
    somebody else. GitHub maps the author from an email address that any committer can set.
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
        if name not in _MANIFESTS and name != PNPM_LOCKFILE:
            problems.append(f"{path} is not an npm manifest or a pnpm lockfile.")
        elif file.get("status") != "modified":
            problems.append(f"{path} is {file.get('status') or 'changed'}, not modified in place.")
    if not problems and not any(PurePosixPath(str(f.get("filename") or "")).name == PNPM_LOCKFILE for f in files):
        problems.append(f"The PR changes no {PNPM_LOCKFILE}.")
    return problems


def _without(document: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    excluded = set(keys)
    return {key: value for key, value in document.items() if key not in excluded}


def _numeric_version(version: str) -> tuple[int, ...]:
    match = _NUMERIC_VERSION_RE.match(version)
    return tuple(int(part or 0) for part in match.groups()) if match else ()


def _release_line(version: str) -> tuple[int, ...] | None:
    """The versions that ``update_refusal`` treats as compatible: one major, or one minor below 1.0."""
    numeric = _numeric_version(version)
    if not numeric:
        return None
    return numeric[:1] if numeric[0] else numeric[:2]


def update_refusal(change: VersionChange) -> str | None:
    """Why a change is not a minor or patch update, or None.

    It matches the updates Renovate automerges here, which exclude 0.x minors. A version that does
    not start with two numbers counts as major, and a rollback can return to a vulnerable release.
    """
    old_line = _release_line(change.old_version)
    if old_line is None or old_line != _release_line(change.new_version):
        return "a major update"
    if _numeric_version(change.new_version) < _numeric_version(change.old_version):
        return "a downgrade"
    # The numeric comparison above ignores prerelease tags, so it cannot order 1.2.0-rc.2 against
    # 1.2.0-rc.1 or 1.2.0. Every new prerelease needs a human.
    if "-" in change.new_version:
        return "a prerelease"
    return None


def _npm_range_map_problems(path: str, field: str, base: Any, head: Any) -> list[str]:
    if not isinstance(base, dict) or not isinstance(head, dict):
        return [f"{path} changes the shape of {field}."]
    if set(base) != set(head):
        return [f"{path} adds or removes an entry in {field}."]
    problems = []
    for name, value in head.items():
        if value == base[name]:
            continue
        if not (isinstance(value, str) and _NPM_RANGE_RE.match(value)):
            problems.append(f"{path} sets {field}.{name} to something other than an exact, caret or tilde version.")
        elif refusal := update_refusal(
            VersionChange(name=name, old_version=str(base[name]).lstrip("^~"), new_version=value.lstrip("^~"))
        ):
            problems.append(f"{path} moves {field}.{name} from {base[name]} to {value}, {refusal}.")
    return problems


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


def _excluded_name_pattern(entry: str) -> str:
    """The package name pattern of an exclude entry such as ``semver@5.7.2 || 6.3.1`` or ``@posthog/*``."""
    version_at = entry.find("@", 1)
    return entry[:version_at] if version_at > 0 else entry


def pnpm_policy_problems(workspace_path: str, base_text: str | None, changes: Iterable[VersionChange]) -> list[str]:
    """The merge-base settings that make pnpm check each new version.

    An update is refused for a package that pnpm exempts from a check, or one whose install scripts
    pnpm runs.
    """
    settings = yaml.safe_load(base_text) if base_text is not None else None
    if not (
        isinstance(settings, dict)
        and type(settings.get("minimumReleaseAge")) is int
        and settings["minimumReleaseAge"] > 0
        and settings.get("minimumReleaseAgeStrict") is not False
        and settings.get("trustPolicy") == "no-downgrade"
        and not _PNPM_WEAKENING_SETTINGS & settings.keys()
    ):
        return [
            f"{workspace_path} does not make pnpm enforce a strict minimumReleaseAge and trustPolicy: no-downgrade, "
            f"or it sets one of {', '.join(sorted(_PNPM_WEAKENING_SETTINGS))}, so nothing checks the new versions."
        ]
    excluded = [
        _excluded_name_pattern(str(entry))
        for key in ("minimumReleaseAgeExclude", "trustPolicyExclude")
        for entry in settings.get(key) or []
    ]
    # pnpm reads `!name` as "every package except name", which fnmatch cannot express.
    if any(pattern.startswith("!") for pattern in excluded):
        return [f"{workspace_path} negates an exclude pattern, so its exemptions cannot be read."]
    allow_builds = settings.get("allowBuilds") or {}
    built = {name for name, allowed in allow_builds.items() if allowed} if isinstance(allow_builds, dict) else set()
    built.update(str(name) for name in settings.get("onlyBuiltDependencies") or [])
    problems = []
    for change in changes:
        if any(fnmatchcase(change.name, pattern) for pattern in excluded):
            problems.append(f"{workspace_path} exempts {change.name} from the release age or trust policy.")
        elif change.name in built:
            problems.append(f"{workspace_path} lets {change.name} run install scripts.")
    return problems


def pnpm_workspace_problems(path: str, base_text: str, head_text: str) -> list[str]:
    base, head = yaml.safe_load(base_text) or {}, yaml.safe_load(head_text) or {}
    if not isinstance(base, dict) or not isinstance(head, dict):
        return [f"{path} is not a YAML mapping."]
    if _without(base, ("catalog",)) != _without(head, ("catalog",)):
        return [f"{path} changes settings other than catalog versions."]
    return _npm_range_map_problems(path, "catalog", base.get("catalog", {}), head.get("catalog", {}))


def _replaced_version(base_versions: list[str], *, kept: set[str], new_version: str) -> str:
    """The base version a new one replaces: the highest in its release line, preferring ones the head drops.

    Pairing by release line keeps two updates of one package from pairing by lockfile order, and
    the highest candidate catches a downgrade from any of them.
    """
    candidates = [version for version in base_versions if version not in kept] or base_versions
    new_line = _release_line(new_version)
    same_line = [version for version in candidates if new_line is not None and _release_line(version) == new_line]
    return max(same_line or candidates, key=_numeric_version)


def _split_pnpm_key(key: str) -> LockedPackage | None:
    name, separator, version = key.rpartition("@")
    if not separator or not _NPM_NAME_RE.match(name) or not _VERSION_RE.match(version):
        return None
    return LockedPackage(name=name, version=version)


def pnpm_lock_versions(path: str, base_text: str, head_text: str) -> tuple[list[VersionChange], list[str]]:
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
            base_versions.setdefault(parsed.name, []).append(parsed.version)

    changes: list[VersionChange] = []
    problems: list[str] = []
    for key, entry in head_packages.items():
        if key in base_packages:
            if entry != base_packages[key]:
                problems.append(f"{path} changes the entry of {key} without changing its version.")
            continue
        parsed = _split_pnpm_key(key)
        if parsed is None:
            problems.append(f"{path} locks an entry that is not a plain registry package.")
            continue
        name, version = parsed.name, parsed.version
        if name not in base_versions:
            problems.append(f"{path} adds {name}, which it did not lock before.")
            continue
        # A tarball, a git repository or a directory carries more keys than the integrity hash.
        entry = entry or {}
        if set(entry.get("resolution") or {}) != {"integrity"} or not set(entry) <= _PNPM_REGISTRY_ENTRY_KEYS:
            problems.append(f"{path} resolves {name}@{version} from somewhere other than the registry.")
            continue
        changes.append(
            VersionChange(
                name=name,
                old_version=_replaced_version(
                    base_versions[name],
                    kept={v for v in base_versions[name] if f"{name}@{v}" in head_packages},
                    new_version=version,
                ),
                new_version=version,
            )
        )
    return changes, problems


def verify_renovate_update(
    *,
    pr: Mapping[str, Any],
    repo: str,
    commits: list[dict[str, Any]],
    files: list[dict[str, Any]],
    merge_base_sha: str,
    head_sha: str,
    read_file: ReadFile,
) -> RenovateVerification:
    """Run every check and collect each problem. ``read_file`` returns a path's text at a commit, or None."""
    if not is_renovate_pr(pr, repo):
        return RenovateVerification(problems=("GitHub does not attest this PR as Renovate's.",))
    problems = [*commit_problems(commits, head_sha), *changed_file_problems(files)]
    if problems:
        return RenovateVerification(problems=tuple(problems))

    locked: list[VersionChange] = []
    cleared: list[str] = []
    for file in files:
        path = str(file["filename"])
        base_text, head_text = read_file(path, merge_base_sha), read_file(path, head_sha)
        if base_text is None or head_text is None:
            problems.append(f"{path} could not be read at both the merge base and the head.")
            continue
        try:
            if PurePosixPath(path).name == PNPM_LOCKFILE:
                found, lock_problems = pnpm_lock_versions(path, base_text, head_text)
                workspace_path = str(PurePosixPath(path).with_name(PNPM_WORKSPACE))
                locked.extend(found)
                problems.extend(lock_problems)
                problems.extend(pnpm_policy_problems(workspace_path, read_file(workspace_path, merge_base_sha), found))
                cleared.append(path)
                continue
            manifest_check = (
                pnpm_workspace_problems if PurePosixPath(path).name == PNPM_WORKSPACE else package_json_problems
            )
            problems.extend(manifest_check(path, base_text, head_text))
        except (ValueError, yaml.YAMLError, TypeError, AttributeError):
            problems.append(f"{path} does not parse.")

    # Two lockfiles can lock the same version, so the list keeps the first copy of each change.
    changes = tuple(dict.fromkeys(locked))
    problems.extend(
        f"{c.name} {c.old_version} -> {c.new_version} is {refusal}." for c in changes if (refusal := update_refusal(c))
    )
    # A lockfile is cleared only by a verified result, so no consumer can clear one that a problem names.
    return RenovateVerification(
        problems=tuple(dict.fromkeys(problems)),
        changes=changes,
        cleared_paths=tuple(cleared) if changes and not problems else (),
    )
