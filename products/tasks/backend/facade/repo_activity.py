"""Facade re-export for repository commit-activity collection.

Runs one deterministic ``git log`` pass against a history-only clone in a
short-lived sandbox and returns plain data — no agent, no ORM models. Kept out
of ``facade/api.py`` so the heavy sandbox dependencies stay off the light
data-surface import path.
"""

from products.tasks.backend.logic.services.repo_commit_activity import (
    RepositoryCommitActivity,
    RepositoryCommitActivityError,
    collect_repository_commit_activity,
)

__all__ = [
    "RepositoryCommitActivity",
    "RepositoryCommitActivityError",
    "collect_repository_commit_activity",
]
