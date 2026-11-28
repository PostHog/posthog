"""Exceptions raised by the visual_review business logic."""

from __future__ import annotations

from uuid import UUID

from posthog.dataclasses import frozen


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
    """Approval blocked because a newer run exists for this PR. Names that run when it is known."""

    def __init__(self, message: str, head_run_id: UUID | None = None, head_commit_sha: str = "") -> None:
        super().__init__(message)
        self.head_run_id = head_run_id
        self.head_commit_sha = head_commit_sha


@frozen
class RejectedSnapshot:
    identifier: str
    by_id: int | None
    reason: str


class RunNotFullyResolvedError(Exception):
    """Finalize blocked because some changed/new snapshots are still unreviewed or rejected.

    Visual review is all-or-nothing: the baseline is only committed once every
    changed/new snapshot is approved or tolerated. Committing a subset is pointless
    (CI re-detects the rest on the next run) and would green the gate over unreviewed
    changes.
    """

    def __init__(
        self,
        message: str,
        rejected: list[RejectedSnapshot] | None = None,
        needs_review: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.rejected = rejected or []
        self.needs_review = needs_review or []


@frozen
class DecisionRefusal:
    """Why one snapshot of a decision call was refused. A `conflict` is a 409, the rest are 400s."""

    identifier: str
    code: str
    detail: str
    conflict: bool
    # The seq of the newest decision on the snapshot's pictures, when the refusal is about that decision.
    current_seq: int | None = None


class SnapshotRejectedError(Exception):
    """A toleration refused because the pull request's newest decision on the pair is a rejection."""

    pass


class DecidedByPersonError(Exception):
    """A toleration by an agent refused because a person made the newest decision on the pair."""

    pass


class DecisionRefusedError(Exception):
    """A review decision call refused as a whole, because at least one snapshot could not take the decision.

    The call is all or nothing, so `refusals` names every refused snapshot. The code and the
    status come from the first refusal.
    """

    def __init__(self, refusals: list[DecisionRefusal]) -> None:
        self.refusals = refusals
        self.code = refusals[0].code
        self.conflict = refusals[0].conflict
        super().__init__(" ".join(dict.fromkeys(refusal.detail for refusal in refusals)))


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


class BaselineRepairError(Exception):
    """The ledger cannot be repaired against the baseline file now."""

    pass


class BaselineAdoptionError(Exception):
    """The ledger cannot be set to what the chosen run rendered."""

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
