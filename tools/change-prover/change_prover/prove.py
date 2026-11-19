"""Prove one pull request's dependency update from the default branch and the merge base.

This is the shell: it reads git, the GitHub API, the npm registry and PyPI, and runs pnpm. Every
refusal is decided in `change_prover.core`.
"""

from __future__ import annotations

import os
import json
import time
import subprocess
import http.client
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from change_prover.core import identity, issuer, policy, python_sdk
from change_prover.core.lockfile_yaml import comparable, load_yaml
from change_prover.core.policy import LOCKFILE, MANIFEST, WORKSPACE_FILE, join
from change_prover.core.replay import replay_commands

REGISTRY = "https://registry.npmjs.org/"
PYPI = "https://pypi.org/"
PAGE_SIZE = 100
# Every file pnpm reads to write a lockfile without installing.
REPLAY_FILES = (MANIFEST, LOCKFILE, WORKSPACE_FILE, ".npmrc", "*.patch")
# git's well-known id of the empty tree, which git knows without the object being stored.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
Runner = Callable[[list[str], Path], None]


@dataclass(frozen=True)
class IdentifyRequest:
    repository: str
    base_branch: str
    head_sha: str


@dataclass(frozen=True)
class ProveRequest:
    head_sha: str
    workflow_sha: str
    merge_base: str
    merge_base_dir: Path
    lane: str


@dataclass(frozen=True)
class Identified:
    pr: int
    merge_base: str
    lane: str


@dataclass(frozen=True)
class Proof:
    files: list[str]
    blobs: dict[str, str | None]


class Git:
    """Reads trees from the object database, so a sparse checkout is enough. Hooks never run."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def run(self, *args: str) -> bytes:
        command = ["git", "-c", "core.hooksPath=/dev/null", *args]
        return subprocess.run(command, cwd=self.repo, check=True, capture_output=True).stdout

    def fetch(self, *shas: str) -> None:
        self.run("fetch", "--no-tags", "--depth=1", "origin", *shas)

    def blob(self, ref: str, path: str) -> str | None:
        """The blob id at ref:path, or None when absent."""
        line = self.run("ls-tree", ref, "--", path).decode()
        if not line:
            return None
        mode, kind, oid = line.split("\t", 1)[0].split()
        policy.check_regular_file(path, mode, kind)
        return oid

    def tree(self, ref: str, path: str) -> str | None:
        """The tree id of the directory at ref:path, or None when absent."""
        line = self.run("ls-tree", ref, "--", path.removesuffix("/")).decode()
        if not line:
            return None
        _mode, kind, oid = line.split("\t", 1)[0].split()
        if kind != "tree":
            raise issuer.InvalidIssuerManifest(f"{path} is not a directory")
        return oid

    def show(self, ref: str, path: str) -> bytes | None:
        oid = self.blob(ref, path)
        return None if oid is None else self.run("cat-file", "blob", oid)

    def changed_files(self, base: str, head: str) -> list[policy.ChangedFile]:
        fields = self.run("diff", "--name-status", "--no-renames", "-z", base, head).decode().split("\0")
        return [policy.ChangedFile(status, path) for status, path in zip(fields[0::2], fields[1::2])]

    def commit_time(self, sha: str) -> datetime:
        return datetime.fromtimestamp(int(self.run("log", "-1", "--format=%ct", sha)), UTC)

    def raw_commit(self, sha: str) -> bytes:
        return self.run("cat-file", "commit", sha)

    def tree_id(self, ref: str) -> str:
        return self.run("rev-parse", "--verify", f"{ref}^{{tree}}").decode().strip()

    def changed_paths(self, base: str, tree: str) -> list[str]:
        listed = self.run("diff", "--name-only", "--no-renames", "-z", base, tree).decode().split("\0")
        return [path for path in listed if path]

    def merge_tree(self, merge_base: str, ours: str, theirs: str) -> tuple[int, bytes]:
        """The exit code and output of `git merge-tree --write-tree`, which writes the result as a tree only.

        A `.gitattributes` file can select a merge driver such as `union`, which turns a conflict
        into a clean merge, and a non-bare repository reads it from the working tree. So git reads
        attributes only from the empty tree, and from no global or system file.
        """
        command = [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.attributesFile=/dev/null",
            f"--attr-source={EMPTY_TREE}",
            "merge-tree",
            "--write-tree",
            "--no-messages",
            f"--merge-base={merge_base}",
            ours,
            theirs,
        ]
        env = {**os.environ, "GIT_ATTR_NOSYSTEM": "1"}
        done = subprocess.run(command, cwd=self.repo, capture_output=True, env=env)
        return done.returncode, done.stdout

    def add_worktree(self, directory: Path, sha: str) -> None:
        self.run("worktree", "add", "--detach", str(directory), sha)
        # A new worktree copies the sparse patterns of the checkout it comes from, which hold no manifest.
        self.run("-C", str(directory), "sparse-checkout", "set", "--no-cone", *REPLAY_FILES)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Fails a redirect, because urllib would send the Authorization header on to the new host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(request: urllib.request.Request, attempts: int = 3) -> bytes:
    """A GET with retries on transport errors and 5xx. Anything else fails the proof."""
    if request.type != "https":
        raise ValueError(f"refusing a non-https URL: {request.full_url}")
    for attempt in range(attempts):
        try:
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- the scheme is checked above, and every caller builds the URL from a constant https origin
            with OPENER.open(request, timeout=60) as response:
                return response.read()
        # A body cut short raises IncompleteRead, which is an HTTPException and not an OSError.
        except (OSError, http.client.HTTPException) as error:
            if attempt == attempts - 1 or (isinstance(error, urllib.error.HTTPError) and error.code < 500):
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        self.repository, self.token = repository, token

    def get(self, path: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return json.loads(
            fetch(urllib.request.Request(f"https://api.github.com/repos/{self.repository}/{path}", headers=headers))
        )

    def find(self, path: str) -> Any | None:
        """The same answer as `get`, or None when GitHub answers 404."""
        try:
            return self.get(path)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def pull_requests(self, head_sha: str, base_branch: str) -> list[dict[str, Any]]:
        """The open pull requests into the base branch whose head is this commit."""
        listed = self.get(f"commits/{head_sha}/pulls?per_page={PAGE_SIZE}")
        return identity.open_pulls_at_head(listed, head_sha, base_branch, PAGE_SIZE)

    def pusher_id(self, branch: str, head_sha: str) -> int | None:
        """The account whose push last put the branch at this commit, or None when no listed push did."""
        ref = urllib.parse.quote(f"refs/heads/{branch}", safe="")
        pushes = self.get(f"activity?ref={ref}&per_page={PAGE_SIZE}")
        return next(((push.get("actor") or {}).get("id") for push in pushes if push["after"] == head_sha), None)

    def changed_paths(self, number: int) -> list[str]:
        """The paths a pull request changes."""
        return identity.changed_paths(self.get(f"pulls/{number}/files?per_page={PAGE_SIZE}"), PAGE_SIZE)

    def merge_base(self, base_branch: str, head_sha: str) -> str:
        return self.get(f"compare/{base_branch}...{head_sha}?per_page=1")["merge_base_commit"]["sha"]


class PyPI:
    """Reads PyPI's JSON API and the provenance of each release file."""

    def get(self, path: str) -> Any | None:
        """A PyPI JSON document, or None when PyPI has none at that path."""
        request = urllib.request.Request(PYPI + path, headers={"Accept": "application/json"})
        try:
            return json.loads(fetch(request))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def release(self, name: str, version: str) -> Any:
        path = f"pypi/{name}/{version}/json"
        return python_sdk.require_document(path, self.get(path))

    def provenance(self, name: str, version: str, filename: str) -> Any:
        path = f"integrity/{name}/{version}/{urllib.parse.quote(filename)}/provenance"
        return python_sdk.require_document(path, self.get(path))


def registry_metadata(name: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        REGISTRY + urllib.parse.quote(name, safe="@"), headers={"Accept": "application/json"}
    )
    return json.loads(fetch(request))


def run_command(command: list[str], cwd: Path) -> None:
    # The `GITHUB_*` variables name the files the runner reads step outputs and environment changes
    # from, and a package manager has no use for them.
    env = {name: value for name, value in os.environ.items() if not name.startswith("GITHUB_")}
    subprocess.run(command, cwd=cwd, check=True, env=env)


def replay_lockfile(
    worktree: Path,
    directory: str,
    head_files: Mapping[str, bytes],
    commands: list[list[str]],
    release_age_minutes: Callable[[], int],
    run: Runner,
) -> bytes:
    """The lockfile pnpm writes in the merge-base tree once the head manifests and workspace file are in place.

    `check_workspace_text` holds the head workspace file to the default branch's settings, so pnpm
    runs with those settings and the pull request's catalog.

    Each command sees the registry as Renovate saw it at the head commit. pnpm counts
    `minimumReleaseAge` back from now, so the age it gets is the policy's release age plus the time
    since the head commit. That hides everything published since the head commit, which keeps caret
    ranges and `latest` dist-tags from resolving to newer versions. A package that
    `minimumReleaseAgeExclude` names stays exempt, and `blocked_reason` refuses an update that adds
    or changes one.
    """
    for path, text in head_files.items():
        (worktree / path).write_bytes(text)
    for command in commands:
        run([*command, f"--config.minimumReleaseAge={release_age_minutes()}"], worktree / directory)
    return (worktree / join(directory, LOCKFILE)).read_bytes()


def identify(request: IdentifyRequest, github: GitHub) -> Identified | None:
    """The pull request to prove at the requested head, or None when no author there may have a proof.

    The answer depends on the head commit and not on the run. Anyone can start a run for a head,
    by reopening the pull request or by opening another one at the same commit from a fork, and
    that run reaches the same answer.
    """
    head = request.head_sha
    pr = identity.pick_pull_request(github.pull_requests(head, request.base_branch))
    if pr is None:
        return None
    lane = identity.author_lane(pr, github.changed_paths(pr["number"]))
    if lane is None:
        return None
    identity.check_head_repository(pr, request.repository)
    identity.check_pusher(pr, github.pusher_id(pr["head"]["ref"], head))
    return Identified(pr["number"], github.merge_base(request.base_branch, head), lane)


def issuer_pins(git: Git, workflow_sha: str) -> dict[str, str]:
    """Each path of the issuer manifest at the workflow commit, pinned to its tree or blob id.

    The manifest is read from the object database rather than the working tree, so the pins
    describe the commit the workflow runs from.
    """
    text = git.show(workflow_sha, issuer.MANIFEST_PATH)
    if text is None:
        raise issuer.InvalidIssuerManifest(f"{issuer.MANIFEST_PATH} is missing")
    pins: dict[str, str] = {}
    for path in issuer.parse_manifest(text, issuer.MANIFEST_PATH):
        oid = git.tree(workflow_sha, path) if issuer.is_directory(path) else git.blob(workflow_sha, path)
        if oid is None:
            raise issuer.InvalidIssuerManifest(f"{issuer.MANIFEST_PATH} names {path}, which is missing")
        pins[path] = oid
    return pins


def lockfile_groups(files: list[str], git: Git, merge_base: str) -> dict[str, list[str]]:
    """Changed manifests keyed by the directory of the nearest lockfile at or above them."""
    groups: dict[str, list[str]] = {}
    for path in files:
        directory = policy.lockfile_dir(path, lambda candidate: git.blob(merge_base, candidate) is not None)
        manifests = groups.setdefault(directory, [])
        name = path.rpartition("/")[2]
        if name == MANIFEST:
            manifests.append(path)
        elif name == WORKSPACE_FILE:
            policy.check_beside_lockfile(path, directory)
    return groups


def prove_group(
    git: Git,
    registry: Callable[[str], Mapping[str, Any]],
    run: Runner,
    now: datetime,
    worktree: Path,
    workflow_sha: str,
    merge_base: str,
    head: str,
    directory: str,
    manifests: list[str],
    release_age_minutes: Callable[[], int],
) -> set[str]:
    """Proves one lockfile directory and returns the settings paths its proof read.

    The steps run cheapest first, so a refusal that needs only git comes before any registry
    lookup or pnpm run.
    """

    def read(ref: str, path: str) -> bytes:
        return policy.require_file(path, git.show(ref, path))

    lockfile, root_manifest = join(directory, LOCKFILE), join(directory, MANIFEST)
    workspace_path = join(directory, WORKSPACE_FILE)
    # A lockfile directory without a workspace file is refused, because pnpm would then read the
    # settings of a workspace file above it, and this proof judges the directory's own.
    default_text, base_text, head_text = (read(ref, workspace_path) for ref in (workflow_sha, merge_base, head))
    policy.check_workspace_text(workspace_path, default_text, head_text)
    workspace = load_yaml(default_text)
    moved = policy.check_workspace(workspace_path, workspace, load_yaml(base_text), load_yaml(head_text))
    settings = policy.settings_paths(directory, workspace)
    for path in settings:
        if path == workspace_path:
            continue
        policy.check_settings_file(path, git.blob(head, path), git.blob(workflow_sha, path))
    default_manifest = policy.load_manifest(read(workflow_sha, root_manifest))
    head_manifest = policy.load_manifest(read(head, root_manifest))
    policy.check_pnpm_settings(root_manifest, head_manifest, default_manifest)
    only_built = workspace.get("onlyBuiltDependenciesFile")
    blocked = policy.blocked_patterns(
        workspace,
        default_manifest,
        read(workflow_sha, join(directory, str(only_built))).decode() if only_built else None,
    )

    base_lock, head_lock = load_yaml(read(merge_base, lockfile)), comparable(read(head, lockfile))
    head_files = {workspace_path: head_text, **{path: read(head, path) for path in manifests}}
    for path in manifests:
        policy.check_member(path, directory, base_lock)
        policy.check_manifest(
            path, policy.load_manifest(read(merge_base, path)), policy.load_manifest(head_files[path])
        )
    changes = policy.direct_changes(base_lock, head_lock)
    packages = {f"{change.name}@{change.new}" for change in changes} | set(policy.new_packages(base_lock, head_lock))
    policy.check_blocked(packages, blocked)
    bumped = [change for change in changes if change.old != change.new]
    releases = sorted({(change.name, change.new) for change in bumped})
    policy.check_releases(lockfile, releases)
    version = policy.pnpm_version(root_manifest, policy.load_manifest(read(merge_base, root_manifest)))
    for name, release in releases:
        policy.check_release_age(name, release, registry(name), now)

    run(["npm", "install", "--global", "--no-audit", "--no-fund", f"pnpm@{version}"], worktree)
    updates = sorted({f"{change.name}@{change.new}" for change in bumped if not change.range_changed})
    commands = replay_commands(updates, bool(manifests or moved), bool(workspace.get("packages")))
    replayed = replay_lockfile(worktree, directory, head_files, commands, release_age_minutes, run)
    policy.check_replayed(lockfile, comparable(replayed), head_lock)
    return set(settings)


def prove_python_sdk(
    files: list[str], read: Callable[[str, str], bytes], merge_base: str, head: str, pypi: PyPI
) -> None:
    """Proves a first-party Python SDK bump across ``files``, or raises Refused.

    It reads no setting besides the files it changes, and PyPI.
    """
    moves: dict[str, python_sdk.Move] = {}
    locked: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for path in files:
        changed = python_sdk.check_file(path, read(merge_base, path), read(head, path))
        for name, entry in changed.entries.items():
            locked.setdefault(name, []).append((path, entry))
        for name, move in changed.moves.items():
            python_sdk.add_move(moves, path, name, move.old, move.new)
    python_sdk.check_one_version(moves)
    for name, move in sorted(moves.items()):
        held = locked.get(name, [])
        release = pypi.release(name, move.new)
        # A lockfile holds the old release's requirements. A package no lockfile holds has none to go stale.
        old_release = pypi.release(name, move.old) if held else None
        served = python_sdk.check_release(name, move.new, held, release, old_release)
        for filename, sha256 in served.items():
            python_sdk.check_provenance(filename, sha256, pypi.provenance(name, move.new, filename))


def prove(
    request: ProveRequest,
    git: Git,
    registry: Callable[[str], Mapping[str, Any]],
    pypi: PyPI,
    run: Runner,
    now: datetime,
) -> Proof:
    """The proof for the requested pull request, or a Refused saying what stops it."""
    started = time.monotonic()
    head, workflow_sha, merge_base = request.head_sha, request.workflow_sha, request.merge_base

    git.fetch(merge_base, head)
    pins = issuer_pins(git, workflow_sha)
    files = policy.eligible_paths(git.changed_files(merge_base, head), request.lane)
    if request.lane == policy.PYTHON_SDK_LANE:

        def read(ref: str, path: str) -> bytes:
            return policy.require_file(path, git.show(ref, path))

        prove_python_sdk(files, read, merge_base, head, pypi)
        return Proof(files, dict(sorted(pins.items())))
    groups = lockfile_groups(files, git, merge_base)
    worktree = request.merge_base_dir
    git.add_worktree(worktree, merge_base)
    committed = git.commit_time(head)
    policy.check_commit_time(committed, now)

    def release_age_minutes() -> int:
        # pnpm reads its own clock when it runs, which is later than `now` by the time spent since the start.
        since_head = (now - committed).total_seconds() + time.monotonic() - started
        return int(since_head // 60) + 1 + policy.MINIMUM_RELEASE_AGE_MINUTES

    settings: set[str] = set()
    for directory, manifests in groups.items():
        settings |= prove_group(
            git,
            registry,
            run,
            now,
            worktree,
            workflow_sha,
            merge_base,
            head,
            directory,
            manifests,
            release_age_minutes,
        )
    # A settings file may be absent, and its null pin then says the default branch had none.
    blobs = {**{path: git.blob(workflow_sha, path) for path in settings}, **pins}
    return Proof(files, dict(sorted(blobs.items())))
