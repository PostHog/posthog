"""Exceptions raised by the visual_review business logic."""

from __future__ import annotations


class RepoNotFoundError(Exception):
    pass


class RunNotFoundError(Exception):
    pass


class ArtifactNotFoundError(Exception):
    pass


class GitHubIntegrationNotFoundError(Exception):
    """Team does not have a GitHub integration configured."""

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
