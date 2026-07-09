"""Publish local commits as GitHub-signed (Verified) commits.

Replays the local-only commits of the current branch through GitHub's GraphQL
`createCommitOnBranch` mutation. GitHub creates each commit server-side, signs
it with its own key (Verified badge), and authors it as the owner of the gh
CLI token. No local signing key, agent, or human approval is needed, so this
works for unattended agent sessions and satisfies `required_signatures`
rulesets.

Fidelity contract: every commit in the range is validated individually before
anything is published, and content the API cannot represent (merge commits,
symlinks, submodules, executable-bit changes, non-UTF-8 paths or messages) is
refused rather than silently mangled. Commits are replayed onto a temporary
scratch branch and the real branch ref is moved only after the whole chain
succeeds, so a mid-publish failure never leaves the branch half-rewritten.

Two unavoidable normalizations, both documented GitHub API behavior: commit
hashes are rewritten (commits are recreated server-side), and a message whose
body follows the subject without a blank line is reformatted with one (the
API takes headline and body as separate fields).
"""

from __future__ import annotations

import re
import json
import uuid
import base64
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click

from hogli_commands.github_auth import github_token

# createCommitOnBranch has no documented payload cap, but large payloads time
# out or hit the REST blob ceiling (~40 MiB); refuse well before that.
MAX_PAYLOAD_BASE64_BYTES = 30 * 1024 * 1024

_MUTATION = "mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid } } }"

MODE_SYMLINK = "120000"
MODE_SUBMODULE = "160000"
MODE_EXECUTABLE = "100755"
MODE_ABSENT = "000000"


class PublishError(click.ClickException):
    pass


class GitError(PublishError):
    pass


@dataclass(frozen=True)
class RawDiffEntry:
    src_mode: str
    dst_mode: str
    dst_sha: str
    status: str
    path: str


@dataclass(frozen=True)
class CommitPlan:
    sha: str
    headline: str
    body: str
    entries: list[RawDiffEntry]


def _git_bytes(args: list[str], *, stdin: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(["git", *args], input=stdin, capture_output=True, check=True)
    except FileNotFoundError as err:
        raise PublishError("git is not installed or not on PATH.") from err
    except subprocess.CalledProcessError as err:
        stderr = err.stderr.decode(errors="replace").strip()
        raise GitError(f"`git {' '.join(args)}` failed: {stderr or f'exit status {err.returncode}'}") from err
    return result.stdout


def _git_text(args: list[str]) -> str:
    try:
        return _git_bytes(args).decode().strip()
    except UnicodeDecodeError as err:
        raise PublishError(
            f"`git {' '.join(args)}` produced non-UTF-8 output. Non-UTF-8 paths or "
            "commit messages cannot be represented in the GitHub API."
        ) from err


def split_commit_message(raw: str) -> tuple[str, str]:
    headline, _, rest = raw.partition("\n")
    return headline.strip(), rest.removeprefix("\n").rstrip("\n")


def parse_raw_diff(z_output: str) -> list[RawDiffEntry]:
    """Parse `git diff --raw -z --no-abbrev --no-renames` records.

    Each record is `:<src_mode> <dst_mode> <src_sha> <dst_sha> <status>` NUL
    `<path>` NUL. With --no-renames the status is a single letter (A/M/D/T).
    """
    tokens = z_output.split("\0")
    entries: list[RawDiffEntry] = []
    for meta, path in zip(tokens[::2], tokens[1::2]):
        if not meta.startswith(":"):
            continue
        src_mode, dst_mode, _src_sha, dst_sha, status = meta[1:].split(" ")
        entries.append(RawDiffEntry(src_mode=src_mode, dst_mode=dst_mode, dst_sha=dst_sha, status=status, path=path))
    return entries


def mode_violations(entries: list[RawDiffEntry]) -> list[str]:
    """Content the API silently mangles: refuse instead of publishing it.

    createCommitOnBranch creates new files as 100644 and preserves an existing
    file's mode on content edits, so new executables and any mode transition
    are unrepresentable; content edits of an existing executable are fine.
    """
    violations: list[str] = []
    for e in entries:
        if MODE_SYMLINK in (e.src_mode, e.dst_mode):
            violations.append(f"{e.path}: symlinks become regular files via the API")
        elif MODE_SUBMODULE in (e.src_mode, e.dst_mode):
            violations.append(f"{e.path}: submodule changes cannot be represented via the API")
        elif e.src_mode == MODE_ABSENT and e.dst_mode == MODE_EXECUTABLE:
            violations.append(f"{e.path}: new files lose the executable bit via the API")
        elif (
            MODE_EXECUTABLE in (e.src_mode, e.dst_mode)
            and e.src_mode != e.dst_mode
            and MODE_ABSENT not in (e.src_mode, e.dst_mode)
        ):
            violations.append(f"{e.path}: executable-bit changes cannot be represented via the API")
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
    match = re.match(r"^(?:https://|ssh://git@|git@)github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise PublishError(f"Origin is not a github.com repository: {url}")
    return match.group(1)


def _default_branch() -> str:
    try:
        return _git_text(["rev-parse", "--abbrev-ref", "origin/HEAD"]).removeprefix("origin/")
    except GitError:
        pass
    # origin/HEAD is often unset in non-cloned checkouts; ask the remote.
    out = _git_text(["ls-remote", "--symref", "origin", "HEAD"])
    match = re.search(r"^ref: refs/heads/(\S+)\tHEAD$", out, re.MULTILINE)
    if not match:
        raise PublishError(
            "Could not determine the remote default branch. Set it locally with "
            "`git remote set-head origin -a` and retry."
        )
    return match.group(1)


def _require_gh_auth() -> None:
    if github_token() is None:
        raise PublishError("No GitHub token available. Run `gh auth login` first.")


def _token_scopes() -> set[str] | None:
    """Best-effort classic-OAuth scope introspection; None when undeterminable
    (fine-grained PATs and GitHub App tokens send no X-OAuth-Scopes header)."""
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


def _commit_entries(commit: str) -> list[RawDiffEntry]:
    return parse_raw_diff(_git_text(["diff", "--raw", "-z", "--no-abbrev", "--no-renames", f"{commit}^", commit]))


def _blob_shas(entries: list[RawDiffEntry]) -> list[str]:
    return list(dict.fromkeys(e.dst_sha for e in entries if e.status != "D"))


def _blob_sizes(shas: list[str]) -> dict[str, int]:
    """Byte size per blob via one `git cat-file --batch-check` call."""
    if not shas:
        return {}
    out = _git_bytes(["cat-file", "--batch-check"], stdin="\n".join(shas).encode())
    sizes: dict[str, int] = {}
    for line in out.decode().splitlines():
        sha, kind, *rest = line.split(" ")
        if kind != "blob" or not rest:
            raise GitError(f"`git cat-file --batch-check` could not resolve blob {sha}: {kind}")
        sizes[sha] = int(rest[0])
    return sizes


def _read_blobs(shas: list[str]) -> dict[str, bytes]:
    """Blob contents via one `git cat-file --batch` call."""
    if not shas:
        return {}
    out = _git_bytes(["cat-file", "--batch"], stdin="\n".join(shas).encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    for _ in shas:
        header_end = out.index(b"\n", pos)
        sha, kind, *rest = out[pos:header_end].decode().split(" ")
        if kind != "blob" or not rest:
            raise GitError(f"`git cat-file --batch` could not resolve blob {sha}: {kind}")
        size = int(rest[0])
        start = header_end + 1
        blobs[sha] = out[start : start + size]
        pos = start + size + 1  # skip the trailing newline after the contents
    return blobs


def _commit_file_changes(entries: list[RawDiffEntry]) -> dict[str, list[dict[str, str]]]:
    blobs = _read_blobs(_blob_shas(entries))
    additions: list[dict[str, str]] = []
    deletions: list[dict[str, str]] = []
    for e in entries:
        if e.status == "D":
            deletions.append({"path": e.path})
        else:
            additions.append({"path": e.path, "contents": base64.b64encode(blobs[e.dst_sha]).decode()})
    return {"additions": additions, "deletions": deletions}


def _commit_message(commit: str) -> str:
    raw = _git_bytes(["show", "-s", "--format=%B", commit])
    try:
        return raw.decode().removesuffix("\n")
    except UnicodeDecodeError as err:
        raise PublishError(
            f"Commit {commit[:10]} has a non-UTF-8 message, which the GitHub API cannot represent."
        ) from err


def _base64_size(raw_size: int) -> int:
    return (raw_size + 2) // 3 * 4


def _plan_commit(commit: str) -> CommitPlan:
    entries = _commit_entries(commit)
    if violations := mode_violations(entries):
        raise PublishError(f"Commit {commit[:10]} cannot be published faithfully:\n  " + "\n  ".join(violations))
    if not entries:
        raise PublishError(f"Commit {commit[:10]} is empty. The API cannot create empty commits.")
    headline, body = split_commit_message(_commit_message(commit))
    if not headline:
        raise PublishError(f"Commit {commit[:10]} has an empty message headline, which the API rejects.")
    sizes = _blob_sizes(_blob_shas(entries))
    if (size := sum(_base64_size(s) for s in sizes.values())) > MAX_PAYLOAD_BASE64_BYTES:
        raise PublishError(
            f"Commit {commit[:10]} is {size / 1024 / 1024:.0f} MB encoded, over the "
            f"{MAX_PAYLOAD_BASE64_BYTES / 1024 / 1024:.0f} MB limit. Split it into smaller commits."
        )
    return CommitPlan(sha=commit, headline=headline, body=body, entries=entries)


def _gh_rest(method: str, path: str, fields: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    args = ["gh", "api", "-X", method, path]
    for key, value in fields.items():
        args += ["-f", f"{key}={value}"]
    return subprocess.run(args, capture_output=True)


def _create_remote_branch(repo: str, branch: str, sha: str) -> None:
    result = _gh_rest("POST", f"repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
    if result.returncode != 0:
        raise PublishError(f"Creating remote branch {branch} failed: {result.stderr.decode().strip()}")


def _fast_forward_remote_branch(repo: str, branch: str, sha: str) -> None:
    result = _gh_rest("PATCH", f"repos/{repo}/git/refs/heads/{branch}", {"sha": sha})
    if result.returncode != 0:
        raise PublishError(
            f"Updating origin/{branch} failed (did it move during the publish?): "
            f"{result.stderr.decode().strip()}. Nothing on {branch} was changed; "
            "fetch, rebase, and retry."
        )


def _delete_remote_branch(repo: str, branch: str) -> None:
    _gh_rest("DELETE", f"repos/{repo}/git/refs/heads/{branch}")


def _create_commit_on_branch(
    repo: str, branch: str, expected_head: str, plan: CommitPlan, changes: dict[str, list[dict[str, str]]]
) -> str:
    commit_message: dict[str, str] = {"headline": plan.headline}
    if plan.body:
        commit_message["body"] = plan.body
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
    )
    if result.returncode != 0:
        stderr = result.stderr.decode().strip()
        hint = (
            ". Your token may lack workflow access: `gh auth refresh -s workflow`"
            if "workflow" in stderr.lower()
            else ""
        )
        raise PublishError(f"createCommitOnBranch failed: {stderr}{hint}")
    oid = json.loads(result.stdout)["data"]["createCommitOnBranch"]["commit"]["oid"]
    assert isinstance(oid, str)
    return oid


def _resolve_publish_base(branch: str, head: str, tip: str | None, default_branch: str) -> str:
    """The remote commit the replayed chain builds on: the branch tip when the
    remote branch exists (refusing if it diverged), else the merge base."""
    if tip is None:
        return _git_text(["merge-base", f"origin/{default_branch}", head])
    if subprocess.run(["git", "cat-file", "-e", f"{tip}^{{commit}}"], capture_output=True).returncode != 0:
        _git_text(["fetch", "--no-tags", "origin", branch])
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", tip, head], capture_output=True)
    if ancestor.returncode == 1:
        raise PublishError(
            f"origin/{branch} has commits you don't have locally. Sync first "
            f"(git fetch origin {branch} && git rebase origin/{branch}), then retry."
        )
    if ancestor.returncode != 0:
        raise GitError(f"`git merge-base --is-ancestor` failed: {ancestor.stderr.decode(errors='replace').strip()}")
    return tip


def _sync_local_branch(branch: str, head: str, new_tip: str) -> None:
    _git_text(["fetch", "--no-tags", "origin", branch])
    if _git_text(["rev-parse", f"{new_tip}^{{tree}}"]) != _git_text(["rev-parse", f"{head}^{{tree}}"]):
        raise PublishError(
            f"Published tree does not match local HEAD. Local branch left at {head[:10]}; "
            f"inspect origin/{branch} before syncing manually."
        )
    # Compare-and-swap so a branch that moved locally mid-publish is never clobbered.
    _git_text(["update-ref", f"refs/heads/{branch}", new_tip, head])
    _git_text(["branch", f"--set-upstream-to=origin/{branch}", branch])


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
        raise PublishError(f"A {op} is in progress. Finish or abort it first.")

    try:
        branch = _git_text(["symbolic-ref", "--short", "HEAD"])
    except GitError as err:
        raise PublishError("Detached HEAD. Check out a branch first.") from err

    default_branch = _default_branch()
    if branch == default_branch:
        raise PublishError(f"Refusing to publish directly to {default_branch}. Create a branch first.")

    repo = _origin_repo()
    head = _git_text(["rev-parse", "HEAD"])

    tip = _remote_tip(branch)
    if tip == head:
        click.echo("Remote branch is already at HEAD. Nothing to publish.")
        return
    base = _resolve_publish_base(branch, head, tip, default_branch)

    commits: list[str] = []
    for row in _git_text(["rev-list", "--reverse", "--parents", f"{base}..{head}"]).splitlines():
        sha, *parents = row.split(" ")
        if len(parents) > 1:
            raise PublishError(
                "The range contains merge commits, which the GitHub API cannot create. "
                "Rebase onto the base branch instead of merging it in, then retry."
            )
        commits.append(sha)
    if not commits:
        raise PublishError("No local commits to publish.")

    plans = [_plan_commit(c) for c in commits]

    if any(workflow_paths(p.entries) for p in plans):
        scopes = _token_scopes()
        if scopes is not None and "workflow" not in scopes:
            raise PublishError(
                "This range touches .github/workflows/ but your gh token lacks the "
                "`workflow` scope. Run `gh auth refresh -s workflow`, then retry."
            )

    if dry_run:
        click.secho(f"Would publish {len(plans)} commit(s) to {repo}:{branch}", bold=True)
        for plan in plans:
            click.echo(f"  {plan.sha[:10]} {plan.headline}")
        return

    _require_gh_auth()

    # Replay onto a scratch branch so the real branch moves all-or-nothing.
    scratch = f"hogli/publish-signed-tmp-{uuid.uuid4().hex[:12]}"
    _create_remote_branch(repo, scratch, base)
    try:
        expected = base
        for plan in plans:
            changes = _commit_file_changes(plan.entries)
            expected = _create_commit_on_branch(repo, scratch, expected, plan, changes)
            click.echo(f"  {plan.sha[:10]} -> {expected[:10]} {plan.headline}")
        if tip is None:
            _create_remote_branch(repo, branch, expected)
        else:
            _fast_forward_remote_branch(repo, branch, expected)
    except Exception:
        _delete_remote_branch(repo, scratch)
        click.secho(f"Publish failed. origin/{branch} was not changed.", fg="red")
        raise
    _delete_remote_branch(repo, scratch)

    _sync_local_branch(branch, head, expected)
    click.secho(f"Published {len(plans)} signed commit(s) to https://github.com/{repo}/tree/{branch}", fg="green")
    click.echo("Local branch now points at the signed history (hashes were rewritten by the API).")
