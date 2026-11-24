"""Which pull request is a clean revert of one merged commit, decided from what git and the API report.

The proof recomputes the revert: it merges the reverted commit's parent onto the pull request's
merge base, with the reverted commit as the merge base of that merge, and compares the result with
the head tree. Equal trees show that the pull request holds that revert and nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from change_prover.core.policy import Refused

# The line `git revert` writes into the message, followed by `.` or by `, reversing`.
REVERT_LINE = re.compile(r"^This reverts commit ([0-9a-f]{40})[.,]", re.MULTILINE)
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
# A staleness check, not a security control: an old commit is more likely to have code built on
# top of it, which a revert breaks without a conflict. The window counts from the proof's run time
# and the server's merge time, because an author can backdate a commit time.
MERGE_WINDOW = timedelta(days=30)
MERGE_TREE_CONFLICT = 1


class RevertMergeFailed(Exception):
    """git could not compute the revert, so the proof cannot say whether it is clean."""


@dataclass(frozen=True)
class Commit:
    """The parents and the message of one raw commit object."""

    parents: tuple[str, ...]
    message: str


def listed_messages(compared: Mapping[str, Any]) -> list[str]:
    """The messages of the pull request's own commits, from one page of the compare API."""
    commits = compared["commits"]
    if compared["total_commits"] > len(commits):
        raise Refused("the pull request has more commits than this proof reads")
    return [commit["commit"]["message"] for commit in commits]


def reverted_commit(messages: list[str]) -> str | None:
    """The one commit the pull request says it reverts, or None when no message says so."""
    reverted = {sha for message in messages for sha in REVERT_LINE.findall(message)}
    if not reverted:
        return None
    if len(reverted) > 1:
        raise Refused(f"the pull request reverts {len(reverted)} commits, and a proof covers one")
    return reverted.pop()


def check_in_merge_base(compared: Mapping[str, Any] | None) -> None:
    """Refuse unless the reverted commit is an ancestor of the merge base, which is on the default branch.

    `compared` is the compare API answer from the reverted commit to the merge base, or None when
    GitHub does not know the commit.
    """
    if compared is None:
        raise Refused("the reverted commit is not in this repository")
    if compared["status"] not in ("ahead", "identical"):
        raise Refused("the reverted commit is not in the merge base of the pull request")


def merge_time(pulls: list[dict[str, Any]], reverted: str, base_branch: str) -> datetime:
    """When the pull request that landed the reverted commit on the base branch was merged.

    Only a pull request whose merge commit is exactly the reverted commit counts. The list also
    names pull requests that only contain the commit, and their merge time says nothing about it.
    """
    landed = [
        pr["merged_at"]
        for pr in pulls
        if pr.get("merged_at") and pr["base"]["ref"] == base_branch and pr.get("merge_commit_sha") == reverted
    ]
    if len(landed) != 1:
        raise Refused(f"no single merged pull request landed the reverted commit on {base_branch}")
    return datetime.fromisoformat(landed[0])


def check_merge_window(merged_at: datetime, now: datetime) -> None:
    if now - merged_at > MERGE_WINDOW:
        raise Refused(f"the reverted commit was merged more than {MERGE_WINDOW.days} days ago")


def parse_commit(raw: bytes) -> Commit:
    """The parents and message of `git cat-file commit` output.

    A shallow fetch hides a commit's parents from `git log`, but not from the raw object.
    """
    header, _, message = raw.decode("utf-8", errors="replace").partition("\n\n")
    parents = tuple(line.removeprefix("parent ") for line in header.splitlines() if line.startswith("parent "))
    return Commit(parents, message)


def check_reverted_commit(commit: Commit) -> None:
    if not commit.parents:
        raise Refused("the reverted commit is a root commit")
    if len(commit.parents) > 1:
        raise Refused("the reverted commit is a merge commit")
    if REVERT_LINE.search(commit.message):
        raise Refused("the reverted commit is itself a revert")


def merged_tree(returncode: int, stdout: bytes) -> str:
    """The tree `git merge-tree --write-tree` wrote, or a refusal when the revert conflicts.

    Any exit code other than 0 and 1 means git failed, which proves nothing either way.
    """
    if returncode == MERGE_TREE_CONFLICT:
        raise Refused("the reverted commit does not revert cleanly onto the merge base")
    if returncode != 0:
        raise RevertMergeFailed(f"git merge-tree exited with {returncode}")
    tree = stdout.decode().partition("\n")[0]
    if not COMMIT_SHA.fullmatch(tree):
        raise RevertMergeFailed("git merge-tree printed no tree id")
    return tree


def check_head_tree(revert_tree: str, head_tree: str) -> None:
    if revert_tree != head_tree:
        raise Refused("the pull request differs from a clean revert")


def check_changes(files: list[str]) -> None:
    if not files:
        raise Refused("the revert changes no file")
