"""Prove that one pull request is a clean revert of one merged commit.

This is the shell: it reads git and the GitHub API. Every refusal is decided in
`change_prover.core`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from change_prover.core import identity, revert
from change_prover.prove import PAGE_SIZE, Git, GitHub, IdentifyRequest, Proof, issuer_pins


@dataclass(frozen=True)
class RevertProveRequest:
    head_sha: str
    workflow_sha: str
    merge_base: str
    reverted: str


@dataclass(frozen=True)
class RevertIdentified:
    """The pull request at the head and its merge base. `reverted` is None when it reverts nothing."""

    pr: int
    merge_base: str
    reverted: str | None


def identify(request: IdentifyRequest, github: GitHub, now: datetime) -> RevertIdentified | None:
    """The pull request to prove at the requested head, or None when no open pull request has it.

    The PR author must have pushed the head. The reverted commit must be an ancestor of the merge base, which puts it on the default
    branch. Its merge time comes from the pull request that landed it, because GitHub sets that
    time, and an author can set a commit time to any value.
    """
    head, base_branch = request.head_sha, request.base_branch
    pr = identity.pick_any_pull_request(github.pull_requests(head, base_branch))
    if pr is None:
        return None
    identity.check_head_repository(pr, request.repository)
    # A push by anyone but the author would let a writer put a revert onto another author's PR,
    # such as a bot's, and borrow that author's standing with stamphog.
    identity.check_pusher(pr, github.pusher_id(pr["head"]["ref"], head))
    compared = github.get(f"compare/{base_branch}...{head}?per_page={PAGE_SIZE}")
    merge_base = compared["merge_base_commit"]["sha"]
    reverted = revert.reverted_commit(revert.listed_messages(compared))
    if reverted is None:
        return RevertIdentified(pr["number"], merge_base, None)
    revert.check_in_merge_base(github.find(f"compare/{reverted}...{merge_base}?per_page=1"))
    pulls = github.get(f"commits/{reverted}/pulls?per_page={PAGE_SIZE}")
    revert.check_merge_window(revert.merge_time(pulls, reverted, base_branch), now)
    return RevertIdentified(pr["number"], merge_base, reverted)


def prove(request: RevertProveRequest, git: Git) -> Proof:
    """The proof that the head tree is the reverted commit's revert onto the merge base, or a Refused."""
    head, merge_base, reverted = request.head_sha, request.merge_base, request.reverted

    git.fetch(merge_base, head, reverted)
    pins = issuer_pins(git, request.workflow_sha)
    commit = revert.parse_commit(git.raw_commit(reverted))
    revert.check_reverted_commit(commit)
    parent = commit.parents[0]
    git.fetch(parent)
    # A three-way merge from the reverted commit to its parent, onto the merge base, is what
    # `git revert` computes.
    returncode, output = git.merge_tree(reverted, merge_base, parent)
    tree = revert.merged_tree(returncode, output)
    revert.check_head_tree(tree, git.tree_id(head))
    files = git.changed_paths(merge_base, tree)
    revert.check_changes(files)
    return Proof(files, dict(sorted(pins.items())))
