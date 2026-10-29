"""Deterministic verification of a Renovate npm dependency-update pull request.

A lockfile selects the third-party code that gets installed, so before stamphog lets its reviewer
judge a Renovate PR, this module proves the shape of the update from facts the PR cannot forge:

- GitHub attests the author, the head branch and the PR's one commit.
- The manifests change only the version specifiers of dependencies that they already declare.
- Every version change, and every changed reference to a locked version, is a minor or patch
  update, and never a minor update below 1.0.
- The lockfile adds no package that it did not already lock, never points a dependency at another
  package, and resolves every new version from the registry by integrity hash alone.

Whether each new version is safe to install is pnpm's check, so the lockfile's `pnpm-workspace.yaml`
must set `minimumReleaseAge` and `trustPolicy: no-downgrade`. Python updates are out of scope:
`uv sync --frozen` checks none of that, so they need a human.

Every check fails closed. The result is verified only when no problem was found and at least one
version changed.
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


def _npm_range_map_problems(path: str, field: str, base: Any, head: Any) -> list[str]:
    if not isinstance(base, dict) or not isinstance(head, dict):
        return [f"{path} changes the shape of {field}."]
    if set(base) != set(head):
        return [f"{path} adds or removes an entry in {field}."]
    return [
        f"{path} sets {field}.{name} to something other than an exact, caret or tilde version."
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


def _excluded_name_pattern(entry: str) -> str:
    """The package name pattern of an exclude entry such as ``semver@5.7.2 || 6.3.1`` or ``@posthog/*``."""
    version_at = entry.find("@", 1)
    return entry[:version_at] if version_at > 0 else entry


def pnpm_policy_problems(workspace_path: str, base_text: str | None, changes: Iterable[VersionChange]) -> list[str]:
    """The workspace settings that make pnpm check each new version, read at the merge base.

    ``minimumReleaseAgeStrict: false`` lets pnpm resolve a version below the release age, and
    ``dangerouslyAllowAllBuilds`` runs the install scripts of every dependency. A package on
    ``minimumReleaseAgeExclude`` or ``trustPolicyExclude`` skips that check, so its update is refused.
    ``pnpm_workspace_problems`` refuses a PR that changes any of these settings.
    """
    settings = yaml.safe_load(base_text) if base_text is not None else None
    if not (
        isinstance(settings, dict)
        and type(settings.get("minimumReleaseAge")) is int
        and settings["minimumReleaseAge"] > 0
        and settings.get("minimumReleaseAgeStrict") is not False
        and settings.get("trustPolicy") == "no-downgrade"
        and settings.get("dangerouslyAllowAllBuilds") is not True
    ):
        return [
            f"{workspace_path} does not make pnpm enforce a strict minimumReleaseAge, trustPolicy: no-downgrade "
            "and its default refusal of dependency install scripts, so nothing checks the new versions."
        ]
    excluded = [
        _excluded_name_pattern(str(entry))
        for key in ("minimumReleaseAgeExclude", "trustPolicyExclude")
        for entry in settings.get(key) or []
    ]
    return [
        f"{workspace_path} exempts {change.name} from the release age or trust policy, so pnpm does not check it."
        for change in changes
        if any(fnmatchcase(change.name, pattern) for pattern in excluded)
    ]


def pnpm_workspace_problems(path: str, base_text: str, head_text: str) -> list[str]:
    base, head = yaml.safe_load(base_text) or {}, yaml.safe_load(head_text) or {}
    if not isinstance(base, dict) or not isinstance(head, dict):
        return [f"{path} is not a YAML mapping."]
    if _without(base, ("catalog",)) != _without(head, ("catalog",)):
        return [f"{path} changes settings other than catalog versions."]
    if "catalog" not in base and "catalog" not in head:
        return []
    return _npm_range_map_problems(path, "catalog", base.get("catalog", {}), head.get("catalog", {}))


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
            if (entry or {}).get("resolution") != (base_packages[key] or {}).get("resolution"):
                problems.append(f"{path} changes the resolution of {key} without changing its version.")
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
        if set((entry or {}).get("resolution") or {}) != {"integrity"}:
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
    return changes, [*problems, *_pnpm_reference_problems(path, base, head)]


def _pnpm_reference_target(name: str, reference: Any, *, alias: bool) -> LockedPackage | None:
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
    return LockedPackage(name=name, version=target) if _VERSION_RE.match(target) else None


def _pnpm_reference_problem(
    path: str,
    owner: str,
    name: str,
    base_reference: Any,
    reference: Any,
    packages: Mapping[str, Any],
    *,
    alias: bool = False,
) -> str | None:
    """A changed reference must select a locked package, the same package as before, in the same release line.

    A reference with no previous one comes from a new version's snapshot, and an alias there
    substitutes a package that no check has seen.
    """
    target = _pnpm_reference_target(name, reference, alias=alias)
    if target is None or f"{target.name}@{target.version}" not in packages:
        return f"{path} points {owner} at {name} through something other than a locked version."
    previous = _pnpm_reference_target(name, base_reference, alias=alias)
    if (previous.name if previous else name) != target.name:
        return f"{path} points {owner} at another package for {name}."
    if previous is None:
        return None
    if refusal := update_refusal(
        VersionChange(name=target.name, old_version=previous.version, new_version=target.version)
    ):
        return f"{path} moves {owner} from {name} {previous.version} to {target.version}, {refusal}."
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


_PNPM_SNAPSHOT_FIELDS = ("dependencies", "optionalDependencies")


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
    # A snapshot key carries the resolved peers, so a peer change renames the snapshot of a version
    # that the base already locked. That version's dependencies are compared like an unchanged key's.
    base_by_version: dict[str, Any] = {}
    for key, snapshot in base_snapshots.items():
        base_by_version.setdefault(key.split("(", 1)[0], snapshot or {})
    for key, snapshot in (head.get("snapshots") or {}).items():
        unsuffixed = key.split("(", 1)[0]
        parsed = _split_pnpm_key(unsuffixed)
        if parsed is None or unsuffixed not in packages:
            problems.append(f"{path} adds a snapshot that matches no locked package.")
            continue
        owner = f"the snapshot of {parsed.name}"
        previous = base_snapshots.get(key) or base_by_version.get(unsuffixed)
        for field in _PNPM_SNAPSHOT_FIELDS:
            references = (snapshot or {}).get(field) or {}
            base_references = (previous or {}).get(field) or {}
            if previous is not None and set(references) != set(base_references):
                problems.append(f"{path} adds or removes a dependency of {owner} without changing its version.")
                continue
            for name, reference in references.items():
                base_reference = base_references.get(name)
                if reference != base_reference and (
                    problem := _pnpm_reference_problem(
                        path, owner, name, base_reference, reference, packages, alias=True
                    )
                ):
                    problems.append(problem)
    return problems


def _manifest_problems(path: str, base_text: str, head_text: str) -> list[str]:
    if PurePosixPath(path).name == PNPM_WORKSPACE:
        return pnpm_workspace_problems(path, base_text, head_text)
    return package_json_problems(path, base_text, head_text)


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
            problems.extend(_manifest_problems(path, base_text, head_text))
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
