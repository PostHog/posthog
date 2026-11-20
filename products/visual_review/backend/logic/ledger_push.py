"""Move the baseline ledgers of a GitHub repository after a push to its default branch.

The push is a hint and nothing more. Nothing from it reaches the ledger: the task reads the
commits from GitHub, as the periodic task does, and the periodic task still moves every ledger
when a push is lost or late.
"""

from collections.abc import Mapping
from datetime import timedelta
from uuid import UUID

import structlog

from posthog.cache_utils import cache_for
from posthog.dataclasses import frozen
from posthog.ingress.dispatch.database import bounded_statement_timeout

from ..models import Repo
from . import ledger_advance

logger = structlog.get_logger(__name__)

# The lookup runs inside the GitHub webhook request that every product shares, so a slow
# database must cost this delivery its hint and not the request its budget.
_LOOKUP_TIMEOUT_MS = 800


@frozen
class _LedgerRepo:
    team_id: int
    repo_id: UUID


# Every default-branch push of every repository the App sees reaches this lookup, so it is held in
# the process and nearly every delivery costs a dict read. The empty answer after a failed read is
# held too, which keeps a slow database to one capped query per minute instead of one per delivery.
# A ledger turned on inside the window is moved by the periodic task until the cache refreshes.
@cache_for(timedelta(minutes=1))
def _ledger_repos_by_github_id() -> Mapping[int, tuple[_LedgerRepo, ...]]:
    try:
        with bounded_statement_timeout(_LOOKUP_TIMEOUT_MS, models=[Repo]):
            repos = ledger_advance.repos_with_ledger()
    except Exception:
        logger.exception("visual_review.baseline_ledger_push_lookup_failed")
        return {}
    by_github_id: dict[int, list[_LedgerRepo]] = {}
    for repo in repos:
        by_github_id.setdefault(repo.repo_external_id, []).append(_LedgerRepo(team_id=repo.team_id, repo_id=repo.id))
    return {github_id: tuple(ledger_repos) for github_id, ledger_repos in by_github_id.items()}


def advance_after_push(github_repo_id: int) -> None:
    """Enqueue one advance for each project whose repo record follows this GitHub repository."""
    ledger_repos = _ledger_repos_by_github_id().get(github_repo_id, ())
    if not ledger_repos:
        return
    from ..tasks.tasks import (  # noqa: PLC0415 — avoids the logic/tasks circular import
        enqueue_baseline_ledger_advance_after_push,
    )

    for ledger_repo in ledger_repos:
        enqueue_baseline_ledger_advance_after_push(ledger_repo.team_id, str(ledger_repo.repo_id))
