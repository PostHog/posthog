# ruff: noqa: T201
"""Credit commits Stamphog already approved on another PR in the same stack.

Stamphog's approval state is per-PR: it reads reviews for one PR number and
nothing else. Folding a stack back into a single PR therefore looks like a pile
of unreviewed work landing on the surviving PR, even though every commit was
approved on the layer it came from, so the fold costs a re-stamp that reviews
nothing new.

This module rebuilds the lost context. It walks the stack rooted at a PR,
collects the commits each layer's Stamphog approval actually covered, and
reduces them to content keys the caller can match delta commits against.

Two invariants keep the credit sound:

Matching is by content, not by SHA, because folding rebases. A commit's key is
its `git diff-tree --raw` output, which names every touched path along with the
pre-image blob OID, the post-image blob OID, both file modes, and the change
status. Two commits share a key only when they turn byte-identical inputs into
byte-identical outputs, which is strictly stronger than `git patch-id` (that
matches a hunk applied against different surrounding content). It also reads
only tree objects, so it costs no blob downloads in the workflow's blobless
clone.

Layer scopes are derived by chaining approved SHAs rather than by asking GitHub
what a PR contains. Layer N's scope is `approved(N-1)..approved(N)`, which
partitions the stack so no commit is ever credited by a layer that did not
review it. Asking the API instead would over-credit: `/pulls/{n}/commits`
reports a PR's scope against its *current* base, so once the fold rewrites or
retargets the branch below, a top layer's approval would appear to cover the
whole stack.
"""

import sys
import json
import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Bounds the stack walk. Each layer costs a PR listing, a timeline read, a
# review read, and a fetch, inside a job with timeout-minutes: 5.
MAX_STACK_DEPTH = 8

# Backstop against crediting an unbounded history if a branch relationship is
# not what this module assumes. A stack deep enough to exceed this is past the
# point where folding is the interesting case.
MAX_CREDITED_COMMITS = 500

_SUBPROCESS_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Approval:
    """A Stamphog APPROVED review: the commit it was recorded against, and when.

    `submitted_at` is only used to order the approval against base-ref changes,
    so it carries GitHub's raw ISO-8601 string rather than a parsed datetime.
    """

    sha: str
    submitted_at: str


@dataclass(frozen=True)
class Credit:
    """What a PR's stack has already had approved, in the two forms callers need.

    `change_keys` answers "was this commit's content approved?" and is what a
    rewritten commit is matched against. `approved_tips` answers "was this
    whole branch approved?", which is what a merge needs: folding by merging a
    layer in produces one merge commit whose second parent is that layer's tip,
    and a merge has no diff of its own to key on.
    """

    change_keys: frozenset[str]
    approved_tips: tuple[str, ...]

    @classmethod
    def none(cls) -> "Credit":
        return cls(change_keys=frozenset(), approved_tips=())


def _run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        check=True,
    ).stdout


def _succeeds(*args: str, cwd: Path | None = None) -> bool:
    return (
        subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        ).returncode
        == 0
    )


def _gh_json(*args: str) -> list | dict:
    return json.loads(_run("gh", "api", *args))


def is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    """`git merge-base --is-ancestor`: rc 0=ancestor, 1=not ancestor, >=2=error.

    Errors fall through to False so callers treat the relation as non-linear
    and dismiss, or withhold credit, rather than granting either. The stderr
    log distinguishes a real force-push from a git plumbing failure.
    """
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if result.returncode not in (0, 1):
        print(
            f"[stack_credit] is_ancestor git error rc={result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )
    return result.returncode == 0


def change_key(sha: str, cwd: Path) -> str | None:
    """Content key for a commit, or None when the commit cannot be credited.

    Merge commits and empty commits both return None. `git diff-tree` prints
    nothing for a merge unless asked to combine parents, so without this guard
    every merge would hash to the digest of the empty string and match every
    other merge, including a dirty one carrying manual conflict edits.

    Rename detection is disabled because it is a whole-tree heuristic: the same
    change can be reported as a rename in one history and as an add plus a
    delete in another, which would break matching across the rewrite.
    """
    parents = _run("git", "rev-list", "--parents", "-n", "1", sha, cwd=cwd).split()[1:]
    if len(parents) >= 2:
        return None
    raw = _run("git", "diff-tree", "--no-commit-id", "--raw", "-r", "--no-renames", sha, cwd=cwd)
    lines = [line for line in raw.splitlines() if line]
    if not lines:
        return None
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _ensure_object(sha: str, pr_number: int, cwd: Path) -> bool:
    """Make `sha` available locally, fetching the PR ref then the bare SHA.

    The bare-SHA fetch is what reaches an approved commit that a force-push has
    since orphaned, which is exactly the state a fold leaves behind.
    """
    if _succeeds("git", "cat-file", "-e", f"{sha}^{{commit}}", cwd=cwd):
        return True
    _succeeds("git", "fetch", "--filter=blob:none", "origin", f"pull/{pr_number}/head", cwd=cwd)
    if _succeeds("git", "cat-file", "-e", f"{sha}^{{commit}}", cwd=cwd):
        return True
    _succeeds("git", "fetch", "--filter=blob:none", "origin", sha, cwd=cwd)
    return _succeeds("git", "cat-file", "-e", f"{sha}^{{commit}}", cwd=cwd)


def merge_base(a: str, b: str, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "merge-base", a, b],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _first_parent(from_sha: str, to_sha: str, cwd: Path) -> list[str]:
    return _run("git", "rev-list", "--first-parent", f"{from_sha}..{to_sha}", cwd=cwd).splitlines()


def _base_ref_changed_since(repo: str, pr_number: int, submitted_at: str) -> bool:
    """Whether the PR was retargeted after `submitted_at`.

    Retargeting widens what a PR's diff covers without re-recording the
    approval, so an approval from before the retarget no longer describes the
    commits the PR now contains. Both timestamps are GitHub's UTC ISO-8601, so
    a string comparison orders them correctly.

    A failed lookup answers True, which withholds credit and leaves the caller
    dismissing exactly as it did before this module existed. The timeline lives
    under /issues/, so the Stamphog app needs issues:read on top of the
    pull-requests permission its other calls use; without it this is the call
    that fails, and the stderr log is what makes that diagnosable rather than
    looking like a stack that never qualifies.
    """
    try:
        events = _gh_json(f"repos/{repo}/issues/{pr_number}/timeline", "--paginate")
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[stack_credit] timeline lookup failed for #{pr_number}, withholding credit: {exc}", file=sys.stderr)
        return True
    return any(
        event.get("event") == "base_ref_changed" and str(event.get("created_at", "")) > submitted_at
        for event in events  # type: ignore[union-attr]
    )


def _child_prs(repo: str, base_branch: str, author: str) -> list[dict]:
    """PRs stacked directly on `base_branch`: the next layer up.

    Restricted to `author`'s own same-repo PRs. A stack is one person's, and on
    a public repo anyone can open a PR against someone else's branch, so this
    keeps a third party from introducing a layer into the chain.
    """
    prs = _gh_json(
        f"repos/{repo}/pulls",
        "-X",
        "GET",
        "-f",
        "state=all",
        "-f",
        f"base={base_branch}",
        "-f",
        "per_page=100",
    )
    return [
        pr
        for pr in prs  # type: ignore[union-attr]
        if pr.get("user", {}).get("login") == author and (pr.get("head", {}).get("repo") or {}).get("full_name") == repo
    ]


def _layer_scope(
    repo: str,
    pr_number: int,
    approval: Approval,
    previous_sha: str,
    cwd: Path,
) -> list[str] | None:
    """Commits this layer's approval covered, or None when it grants no credit.

    Requires the previous layer's approved commit to be an ancestor of this
    one, which proves the layer was built on the exact content Stamphog signed
    off below it. A broken chain means the stack is not the shape assumed here.
    """
    if not _ensure_object(approval.sha, pr_number, cwd):
        return None
    if not is_ancestor(previous_sha, approval.sha, cwd):
        return None
    if _base_ref_changed_since(repo, pr_number, approval.submitted_at):
        return None
    return _first_parent(previous_sha, approval.sha, cwd)


def collect_credit(
    repo: str,
    pr_number: int,
    own_approval: Approval,
    cwd: Path,
    base_ref: str,
    find_approval: Callable[[str, int], Approval | None],
) -> Credit:
    """Everything this PR's stack has already had approved.

    The root layer is the PR's own prior approval; each layer above it is a PR
    the same author stacked on the layer below.
    """
    if not _ensure_object(own_approval.sha, pr_number, cwd):
        return Credit.none()
    if _base_ref_changed_since(repo, pr_number, own_approval.submitted_at):
        return Credit.none()
    root = merge_base(base_ref, own_approval.sha, cwd)
    if root is None:
        return Credit.none()

    root_pr = _gh_json(f"repos/{repo}/pulls/{pr_number}")
    author = root_pr.get("user", {}).get("login")  # type: ignore[union-attr]
    head_ref = root_pr.get("head", {}).get("ref")  # type: ignore[union-attr]
    if not author or not head_ref:
        return Credit.none()

    commits = list(_first_parent(root, own_approval.sha, cwd))
    tips = [own_approval.sha]
    frontier = [(head_ref, own_approval.sha)]
    visited = {pr_number}

    for _ in range(MAX_STACK_DEPTH):
        next_frontier: list[tuple[str, str]] = []
        for branch, previous_sha in frontier:
            for child in _child_prs(repo, branch, author):
                number = child["number"]
                if number in visited:
                    continue
                visited.add(number)
                approval = find_approval(repo, number)
                if approval is None:
                    continue
                scope = _layer_scope(repo, number, approval, previous_sha, cwd)
                if scope is None:
                    continue
                commits.extend(scope)
                tips.append(approval.sha)
                next_frontier.append((child["head"]["ref"], approval.sha))
        if not next_frontier or len(commits) > MAX_CREDITED_COMMITS:
            break
        frontier = next_frontier

    if len(commits) > MAX_CREDITED_COMMITS:
        return Credit.none()

    keys = {change_key(sha, cwd) for sha in commits}
    keys.discard(None)
    return Credit(change_keys=frozenset(keys), approved_tips=tuple(tips))  # type: ignore[arg-type]
