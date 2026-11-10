"""Decide whether a push leaves a standing stamphog approval in place.

GitHub never dismisses an approval automatically. The review workflow therefore retracts
stamphog's approval before every re-review. That is correct for a push that changes code. It is
wrong for the push that dominates a long-lived PR: a merge of the base branch. Such a merge does not
change the PR's own diff, but it still costs the PR its merge readiness. It also forces a full
sandboxed review to derive the same verdict again.

Retention never judges whether a given file matters. It retains on one of two proofs:

- The PR's own diff is byte-identical to the diff that was approved.
- The new head is a merge of the base branch into an approved head, and the merge adds nothing of its
  own. See `base_merge_is_clean`. This proof covers a base merge that also changed a file the PR
  edits, which moves the PR's hunks and so changes its diff text.

Three properties of that comparison are necessary for safety. A review finding caused each one:

- Both sides come from `compare_diff` on two commit shas. `get_pr_files` answers for the head that
  is live when the request runs, and a contributor can move that head.
- The comparison uses diff text, not per-file blob shas. The text carries file modes and renames. A
  blob sha covers contents only, and GitHub's file payload carries no mode.
- The comparison refuses anything that it cannot see. See the guards in `approved_diff_unchanged`.

Do not add an allowlist of harmless files. One existed, and every entry in it was executable
somewhere in this repository. Plain Markdown is executable too, because it ships through
`services/mcp` templates and product `tools.yaml` prompts.
"""

from __future__ import annotations

import re
import tempfile
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.stamphog.backend.logic.github_client import StamphogGitHubClient

# Heads that a run's approval covers in addition to the head it was posted at. The merge handler
# matches an approving run on head_sha alone, so without this record a retained PR merges as
# unapproved.
RETAINED_HEADS_KEY = "retained_head_shas"

# Bounds the list on a PR that takes many base-branch merges. Only the recent heads can still be
# the merged head, so the oldest entries are safe to drop.
MAX_RETAINED_HEADS = 50

# The reasons that an approval survives a push. The webhook skip log records the value.
UNCHANGED_DIFF = "unchanged_diff"
CLEAN_BASE_MERGE = "clean_base_merge"

# Each file that both sides of a base merge changed costs four contents reads. Past this bound the
# push gets a normal review.
MAX_MERGED_FILES = 20

_MERGE_FILE_TIMEOUT_SECONDS = 10

# GitHub compare statuses that make the base sha an ancestor of the head sha.
_DESCENDANT_STATUSES = frozenset({"ahead", "identical"})

_FILE_HEADER_RE = re.compile(r"^(?=diff --git )", re.MULTILINE)

# The only per-file header that the three-way proof accepts: a regular file at an unquoted path, with
# no mode change, rename, copy, creation or deletion. git quotes a path with unusual characters, and
# that quote fails the match.
_PLAIN_EDIT_HEADER_RE = re.compile(
    r"\Adiff --git a/(?P<path>[^\n]+) b/(?P=path)\n"
    r"index [0-9a-f]+\.\.[0-9a-f]+ (?P<mode>100644|100755)\n"
    r"--- a/(?P=path)\n"
    r"\+\+\+ b/(?P=path)\n"
)


# git renders a binary change as this line over an abbreviated blob id, and never as content. Two
# different binaries whose ids share that prefix produce the same line. An attacker can pad one
# binary until its id collides, so a diff that carries this line cannot show whether the content
# changed.
_BINARY_MARKER_RE = re.compile(r"^Binary files\b.*differ$", re.MULTILINE)


def approved_diff_unchanged(approved_diff: str, current_diff: str) -> bool:
    """Whether the PR's own diff is byte-identical to the one that was approved.

    Returns False for everything ambiguous. An empty diff on either side counts as ambiguous rather
    than as "nothing changed". A PR with no changes at all is degenerate, and two blanks compare
    equal, so such a comparison would retain an approval on no evidence. A diff that describes a
    binary change is refused for a sharper reason, see _BINARY_MARKER_RE.
    """
    if not approved_diff.strip() or not current_diff.strip():
        return False
    if _BINARY_MARKER_RE.search(approved_diff) or _BINARY_MARKER_RE.search(current_diff):
        return False
    return approved_diff == current_diff


def _file_sections(diff: str) -> dict[str, str] | None:
    """The diff split per file and keyed by its `diff --git` line, or None for an unexpected shape."""
    sections: dict[str, str] = {}
    for chunk in _FILE_HEADER_RE.split(diff):
        if not chunk:
            continue
        header = chunk.split("\n", 1)[0]
        if not header.startswith("diff --git ") or header in sections:
            return None
        sections[header] = chunk
    return sections


def files_needing_merge_proof(pr_side_diff: str, merged_diff: str) -> list[str] | None:
    """The paths whose content in a merge commit only a three-way merge can account for.

    ``pr_side_diff`` is the PR's own diff at the approved parent of the merge, and ``merged_diff`` is
    the diff from the base parent to the merge commit. A file whose section is byte-identical in both
    diffs needs no proof: the base side did not change it, and the merge kept the PR's version. Any
    other file must be a plain edit on both sides. Returns None when the merge cannot be proven at
    all: different file sets, a binary change, a mode change, a rename, a creation, a deletion, or
    more than MAX_MERGED_FILES files to prove.
    """
    if not pr_side_diff.strip() or not merged_diff.strip():
        return None
    if _BINARY_MARKER_RE.search(pr_side_diff) or _BINARY_MARKER_RE.search(merged_diff):
        return None
    pr_side = _file_sections(pr_side_diff)
    merged = _file_sections(merged_diff)
    # A file in only one diff is content that the merge added or dropped on its own.
    if pr_side is None or merged is None or pr_side.keys() != merged.keys():
        return None
    paths: list[str] = []
    for header, section in pr_side.items():
        if merged[header] == section:
            continue
        pr_side_match = _PLAIN_EDIT_HEADER_RE.match(section)
        merged_match = _PLAIN_EDIT_HEADER_RE.match(merged[header])
        if pr_side_match is None or merged_match is None or pr_side_match["mode"] != merged_match["mode"]:
            return None
        paths.append(pr_side_match["path"])
    if len(paths) > MAX_MERGED_FILES:
        return None
    return paths


def clean_three_way_merge(base: str, ours: str, theirs: str) -> str | None:
    """The result of `git merge-file` on three file versions, or None when the merge has a conflict.

    git's own merge can use a different diff algorithm and produce different text. That difference
    can only refuse a genuine merge, and it cannot accept an edited one, because the caller accepts
    a merge commit only when its content is exactly a clean merge of the two parents.
    """
    with tempfile.TemporaryDirectory(prefix="stamphog-merge-") as temp_dir:
        root = Path(temp_dir)
        paths: list[str] = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            path = root / name
            path.write_bytes(text.encode("utf-8"))
            paths.append(str(path))
        completed = subprocess.run(
            ["git", "merge-file", "-p", *paths],
            capture_output=True,
            timeout=_MERGE_FILE_TIMEOUT_SECONDS,
            check=False,
        )
    # A positive exit code counts the conflicts, and a negative one is an error.
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8")


def base_merge_is_clean(
    client: StamphogGitHubClient, repo: str, *, approved_heads: set[str], head_sha: str, base_sha: str
) -> bool:
    """Whether ``head_sha`` merges the base branch into an approved head and adds nothing of its own.

    The proof has two parts:

    - Lineage. The head has exactly two parents. The first is an approved head. The second is an
      ancestor of ``base_sha``, so it is base-branch content and not a commit that the author made.
    - Content. Every file is either identical to the approved parent's version, as
      `files_needing_merge_proof` shows from the two diffs, or exactly the clean three-way merge of
      the approved parent's version and the base parent's version.

    A conflict resolution fails the proof, because the author wrote that content.
    """
    parents = client.get_commit_parents(repo, head_sha)
    if len(parents) != 2:
        return False
    pr_parent, base_parent = parents
    if pr_parent not in approved_heads:
        return False
    if client.compare_commits(repo, base_parent, base_sha).status not in _DESCENDANT_STATUSES:
        return False
    merge_base = client.compare_commits(repo, base_parent, pr_parent).merge_base_sha
    if not merge_base:
        return False

    # Three-dot compares, so the first diff starts at the merge base and the second at the base parent.
    paths = files_needing_merge_proof(
        client.compare_diff(repo, base_parent, pr_parent), client.compare_diff(repo, base_parent, head_sha)
    )
    if paths is None:
        return False
    for path in paths:
        versions = [client.get_file_at_ref(repo, path, ref) for ref in (merge_base, pr_parent, base_parent, head_sha)]
        if any(version is None or version.kind != "file" for version in versions):
            return False
        base, ours, theirs, merged = (version.text for version in versions if version is not None)
        if clean_three_way_merge(base, ours, theirs) != merged:
            return False
    return True
