"""Publish local commits as GitHub-signed (Verified) commits.

Replays the local-only commits of the current branch through GitHub's GraphQL
`createCommitOnBranch` mutation. GitHub creates each commit server-side, signs
it with its own key (Verified badge), and authors it as the owner of the gh
CLI token — no local signing key, agent, or human approval needed, so this
works for unattended agent sessions and satisfies `required_signatures`
rulesets.

The API cannot represent merge commits, symlinks, submodules, or executable
bits, and it rewrites commit hashes; this command refuses (rather than
silently corrupts) anything it cannot replay faithfully.
"""

from __future__ import annotations

import os
import re
import json
import base64
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click

# createCommitOnBranch has no documented payload cap, but large payloads time
# out or hit the REST blob ceiling (~40 MiB); refuse well before that.
MAX_PAYLOAD_BASE64_BYTES = 30 * 1024 * 1024

_MUTATION = "mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid } } }"

MODE_SYMLINK = "120000"
MODE_SUBMODULE = "160000"
MODE_EXECUTABLE = "100755"


class PublishError(click.ClickException):
    pass


@dataclass(frozen=True)
class RawDiffEntry:
    src_mode: str
    dst_mode: str
    status: str
    path: str


def _git(args: list[str], *, binary: bool = False) -> str | bytes:
    result = subprocess.run(["git", *args], capture_output=True, check=True)
    return result.stdout if binary else result.stdout.decode().strip()


def _git_text(args: list[str]) -> str:
    result = _git(args)
    assert isinstance(result, str)
    return result


def split_commit_message(raw: str) -> tuple[str, str]:
    headline, _, body = raw.partition("\n")
    return headline.strip(), body.strip("\n").rstrip()


def parse_raw_diff(z_output: str) -> list[RawDiffEntry]:
    """Parse `git diff --raw -z --no-renames` records.

    Each record is `:<src_mode> <dst_mode> <src_sha> <dst_sha> <status>` NUL
    `<path>` NUL. With --no-renames the status is a single letter (A/M/D/T).
    """
    tokens = z_output.split("\0")
    entries: list[RawDiffEntry] = []
    for meta, path in zip(tokens[::2], tokens[1::2]):
        if not meta.startswith(":"):
            continue
        src_mode, dst_mode, _src_sha, _dst_sha, status = meta[1:].split(" ")
        entries.append(RawDiffEntry(src_mode=src_mode, dst_mode=dst_mode, status=status, path=path))
    return entries


def mode_violations(entries: list[RawDiffEntry]) -> list[str]:
    """Content the API silently mangles: refuse instead of publishing it."""
    violations: list[str] = []
    for e in entries:
        if MODE_SYMLINK in (e.src_mode, e.dst_mode):
            violations.append(f"{e.path}: symlinks become regular files via the API")
        elif MODE_SUBMODULE in (e.src_mode, e.dst_mode):
            violations.append(f"{e.path}: submodule changes cannot be represented via the API")
        elif e.dst_mode == MODE_EXECUTABLE and e.src_mode != MODE_EXECUTABLE:
            violations.append(f"{e.path}: the executable bit is dropped via the API")
    return violations


def workflow_paths(entries: list[RawDiffEntry]) -> list[str]:
    return [e.path for e in entries if e.path.startswith(".github/workflows/")]


def _operation_in_progress(git_dir: Path) -> str | None:
    markers = {
        "MERGE_HEAD": "merge",
        "CHERRY_PICK_HEAD": "cherry-pick",
        "REVERT_HEAD": "revert",
        "rebase-merge": "rebase",
        "rebase-apply": "rebase",
    }
    for marker, op in markers.items():
        if (git_dir / marker).exists():
            return op
    return None


def _origin_repo() -> str:
    url = _git_text(["remote", "get-url", "origin"])
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise PublishError(f"Could not parse a GitHub repo from origin URL: {url}")
    return match.group(1)


def _gh_token() -> str:
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        raise PublishError("No GitHub token available — run `gh auth login` first.") from err
    token = result.stdout.decode().strip()
    if not token:
        raise PublishError("`gh auth token` returned nothing — run `gh auth login` first.")
    return token


def _gh_env(token: str) -> dict[str, str]:
    return {**os.environ, "GH_TOKEN": token}


def _token_scopes() -> set[str] | None:
    """Best-effort OAuth scope introspection; None when undeterminable."""
    try:
        headers = subprocess.run(
            ["gh", "api", "user", "--include", "--silent"], capture_output=True, check=True
        ).stdout.decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in headers.splitlines():
        name, _, value = line.partition(":")
        if name.strip().lower() == "x-oauth-scopes":
            return {scope.strip() for scope in value.split(",") if scope.strip()}
    return None


def _remote_tip(branch: str) -> str | None:
    out = _git_text(["ls-remote", "origin", f"refs/heads/{branch}"])
    return out.split("\t")[0] if out else None


def _build_file_changes(commit: str) -> dict[str, list[dict[str, str]]]:
    additions: list[dict[str, str]] = []
    deletions: list[dict[str, str]] = []
    name_status = _git_text(["diff", "--name-status", "-z", "--no-renames", f"{commit}^", commit])
    tokens = name_status.split("\0")
    for status, path in zip(tokens[::2], tokens[1::2]):
        if not status:
            continue
        if status == "D":
            deletions.append({"path": path})
        else:
            blob = _git(["cat-file", "blob", f"{commit}:{path}"], binary=True)
            assert isinstance(blob, bytes)
            additions.append({"path": path, "contents": base64.b64encode(blob).decode()})
    return {"additions": additions, "deletions": deletions}


def _payload_size(changes: dict[str, list[dict[str, str]]]) -> int:
    return sum(len(a["contents"]) for a in changes["additions"])


def _create_commit_on_branch(
    token: str, repo: str, branch: str, expected_head: str, message: str, changes: dict[str, list[dict[str, str]]]
) -> str:
    headline, body = split_commit_message(message)
    commit_message: dict[str, str] = {"headline": headline}
    if body:
        commit_message["body"] = body
    payload = {
        "query": _MUTATION,
        "variables": {
            "input": {
                "branch": {"repositoryNameWithOwner": repo, "branchName": branch},
                "expectedHeadOid": expected_head,
                "message": commit_message,
                "fileChanges": changes,
            }
        },
    }
    result = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env=_gh_env(token),
    )
    if result.returncode != 0:
        raise PublishError(f"createCommitOnBranch failed: {result.stderr.decode().strip()}")
    oid = json.loads(result.stdout)["data"]["createCommitOnBranch"]["commit"]["oid"]
    assert isinstance(oid, str)
    return oid


def _create_remote_branch(token: str, repo: str, branch: str, sha: str) -> None:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={sha}"],
        capture_output=True,
        env=_gh_env(token),
    )
    if result.returncode != 0:
        raise PublishError(f"Creating remote branch {branch} failed: {result.stderr.decode().strip()}")


@click.command(name="git:publish-signed")
@click.option("--dry-run", is_flag=True, help="Show what would be published without touching the remote.")
def git_publish_signed(dry_run: bool) -> None:
    """Publish local commits as GitHub-signed (Verified) commits.

    Replays the current branch's unpushed commits through GitHub's API:
    each commit is recreated server-side, signed by GitHub, and authored
    as your gh token's account. Local checkpoint commits stay unsigned
    and private until you publish. Note: published hashes differ from
    the local ones (the local branch is repointed to the new history).
    """
    git_dir = Path(_git_text(["rev-parse", "--absolute-git-dir"]))
    if op := _operation_in_progress(git_dir):
        raise PublishError(f"A {op} is in progress — finish or abort it first.")

    try:
        branch = _git_text(["symbolic-ref", "--short", "HEAD"])
    except subprocess.CalledProcessError as err:
        raise PublishError("Detached HEAD — check out a branch first.") from err

    default_branch = "master"
    try:
        default_branch = _git_text(["rev-parse", "--abbrev-ref", "origin/HEAD"]).removeprefix("origin/")
    except subprocess.CalledProcessError:
        pass
    if branch == default_branch:
        raise PublishError(f"Refusing to publish directly to {default_branch} — create a branch first.")

    repo = _origin_repo()
    head = _git_text(["rev-parse", "HEAD"])

    tip = _remote_tip(branch)
    if tip is not None:
        if tip == head:
            click.echo("Remote branch is already at HEAD — nothing to publish.")
            return
        _git_text(["fetch", "--no-tags", "origin", branch])
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", tip, head], capture_output=True)
        if ancestor.returncode != 0:
            raise PublishError(
                f"origin/{branch} has commits you don't have locally — sync first "
                f"(git fetch origin {branch} && git rebase origin/{branch}), then retry."
            )
        base = tip
    else:
        base = _git_text(["merge-base", f"origin/{default_branch}", head])

    commits = [c for c in _git_text(["rev-list", "--reverse", f"{base}..{head}"]).splitlines() if c]
    if not commits:
        raise PublishError("No local commits to publish.")
    if _git_text(["rev-list", "--min-parents=2", f"{base}..{head}"]):
        raise PublishError(
            "The range contains merge commits, which the GitHub API cannot create — "
            "rebase onto the base branch instead of merging it in, then retry."
        )

    raw_diff = _git_text(["diff", "--raw", "-z", "--no-renames", base, head])
    entries = parse_raw_diff(raw_diff)
    if violations := mode_violations(entries):
        raise PublishError("Cannot publish faithfully via the API:\n  " + "\n  ".join(violations))

    if workflow_paths(entries):
        scopes = _token_scopes()
        if scopes is not None and "workflow" not in scopes:
            raise PublishError(
                "This range touches .github/workflows/ but your gh token lacks the "
                "`workflow` scope — run `gh auth refresh -s workflow`, then retry."
            )

    per_commit_changes = []
    for commit in commits:
        changes = _build_file_changes(commit)
        if not changes["additions"] and not changes["deletions"]:
            raise PublishError(f"Commit {commit[:10]} is empty — the API cannot create empty commits.")
        if (size := _payload_size(changes)) > MAX_PAYLOAD_BASE64_BYTES:
            raise PublishError(
                f"Commit {commit[:10]} is {size / 1024 / 1024:.0f} MB encoded, over the "
                f"{MAX_PAYLOAD_BASE64_BYTES / 1024 / 1024:.0f} MB limit — split it into smaller commits."
            )
        per_commit_changes.append(changes)

    if dry_run:
        click.secho(f"Would publish {len(commits)} commit(s) to {repo}:{branch}", bold=True)
        for commit in commits:
            click.echo(f"  {commit[:10]} {_git_text(['show', '-s', '--format=%s', commit])}")
        return

    token = _gh_token()
    if tip is None:
        _create_remote_branch(token, repo, branch, base)
        click.echo(f"Created origin/{branch} at {base[:10]}")

    expected = base
    for commit, changes in zip(commits, per_commit_changes):
        message = _git_text(["show", "-s", "--format=%B", commit])
        expected = _create_commit_on_branch(token, repo, branch, expected, message, changes)
        click.echo(f"  {commit[:10]} -> {expected[:10]} {split_commit_message(message)[0]}")

    _git_text(["fetch", "--no-tags", "origin", branch])
    if _git_text(["rev-parse", f"{expected}^{{tree}}"]) != _git_text(["rev-parse", f"{head}^{{tree}}"]):
        raise PublishError(
            f"Published tree does not match local HEAD — local branch left at {head[:10]}; "
            f"inspect origin/{branch} before syncing manually."
        )
    _git_text(["reset", "--soft", expected])
    click.secho(f"Published {len(commits)} signed commit(s) to https://github.com/{repo}/tree/{branch}", fg="green")
    click.echo("Local branch now points at the signed history (hashes were rewritten by the API).")
