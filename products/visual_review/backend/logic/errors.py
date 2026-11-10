"""Exceptions raised by the visual_review business logic."""

from __future__ import annotations


class RepoNotFoundError(Exception):
    pass


class RunNotFoundError(Exception):
    pass


class ArtifactNotFoundError(Exception):
    pass


class QuarantineLiftRequestNotFoundError(Exception):
    pass


class GitHubIntegrationNotFoundError(Exception):
    """Team does not have a GitHub integration configured."""

    pass


class LiftCommitUnknownError(Exception):
    """GitHub cannot name the default branch head, so a quarantine lift cannot be scoped to a commit."""

    pass


class GitHubCommitError(Exception):
    """Failed to commit to GitHub."""

    pass


class PRSHAMismatchError(Exception):
    """PR has new commits since this run was created."""

    pass


class HashIntegrityError(Exception):
    """Uploaded image bytes do not match the claimed content hash."""

    pass


class BaselineEntriesLostError(Exception):
    """A merge-queue branch's baseline file lacks entries for stories that still render.

    The queue tests the tree that lands, so the merge would delete these entries from the
    default branch. Every later full run would then report the stories as new.
    """

    def __init__(self, identifiers: list[str]) -> None:
        self.identifiers = identifiers
        shown = ", ".join(identifiers[:10])
        more = f" and {len(identifiers) - 10} more" if len(identifiers) > 10 else ""
        super().__init__(
            f"The baseline file is missing {len(identifiers)} entries for stories that still render: "
            f"{shown}{more}. Merging would delete them from the default branch. Restore them in the "
            "baseline file from the default branch, then queue the pull request again."
        )


class StaleRunError(Exception):
    """Approval blocked because a newer run exists for this PR."""

    pass


class RunNotFullyResolvedError(Exception):
    """Finalize blocked because some changed/new snapshots are still unreviewed.

    Visual review is all-or-nothing: the baseline is only committed once every
    changed/new snapshot is approved or tolerated. Committing a subset is pointless
    (CI re-detects the rest on the next run) and would green the gate over unreviewed
    changes.
    """

    pass


class BaselineFilePathNotConfiguredError(Exception):
    """Repo does not have a baseline file path configured for this run type."""

    pass
