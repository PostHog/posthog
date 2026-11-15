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


class BaselineLedgerExistsError(Exception):
    """The repo already has a baseline ledger, and seeding again would replace it."""

    pass


class BaselineLedgerMissingError(Exception):
    """The repo has no baseline ledger yet."""

    pass


class BaselineBranchRewrittenError(Exception):
    """The ledger's newest commit is not on the default branch's first-parent line any more."""

    pass


class BaselineCommitGapTooLargeError(Exception):
    """The default branch moved further past the ledger than one advance reads."""

    pass


class BaselineAdvanceError(Exception):
    """GitHub could not answer a read that moving the ledger forward depends on."""

    pass


class BaselineResolutionError(Exception):
    """A run cannot tell which ledger baseline it compares against."""

    pass


class PullRequestClosedError(ValueError):
    """Finalize blocked because the run's pull request is closed or merged.

    A ValueError, so the finalize endpoint answers with a 400 and the message, as it does for the
    other refusals of a run that cannot be approved.
    """

    pass


class RunWithoutBaselineRecordError(ValueError):
    """Ledger-mode finalize blocked because the run has no ledger record its approvals could be written from."""

    pass


class BaselineModeChangedError(ValueError):
    """Finalize blocked because the repo's baseline mode changed between its first read and its lock."""

    pass


class CommitStatusGateError(ValueError):
    """The commit status gate and the baseline mode would not fit together."""


class CommitStatusNotPostedError(Exception):
    """GitHub did not take a commit status that a caller has to know about."""


class RunWithoutPullRequestError(ValueError):
    """Ledger-mode finalize blocked because the run has no pull request its approvals could belong to."""
