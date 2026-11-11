"""Coarse CI state of the pull requests reports opened, read from GitHub's status check rollup.

A caller asks about many pull requests at once, so the answers are cached briefly and shared across
callers. A pull request GitHub cannot answer for is left out instead of raising.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping

from django.core.cache import cache

import structlog

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import PullRequestRef
from posthog.models.integration import GitHubIntegration

logger = structlog.get_logger(__name__)

# The pill in a report list needs a glyph, not a live build log, so its CI state is cached longer
# than the detail view's checks. The detail view stays the authoritative, 15s-fresh read of the
# same pull request.
PR_CI_STATUS_CACHE_SECONDS = 60
# How long a pull request GitHub cannot answer for is remembered as unreadable.
PR_CI_STATUS_UNREADABLE_CACHE_SECONDS = 300
# Cached in place of a CI status for a pull request GitHub cannot answer for. Not a member of the
# status vocabulary, so it can never be served to a caller as one.
_PR_CI_STATUS_UNREADABLE = "unreadable"


def pr_ci_statuses_for_references(team_id: int, references: Iterable[PullRequestRef]) -> dict[PullRequestRef, str]:
    """CI rollup per pull request, from the shared cache where it is warm and one batched GitHub
    call per integration for the rest. A pull request GitHub cannot answer for is absent from the
    result: this paints a glyph onto a list, so it degrades to no glyph rather than to an error."""
    resolved: dict[PullRequestRef, str] = {}
    misses_by_repository: dict[str, list[PullRequestRef]] = defaultdict(list)
    for reference in dict.fromkeys(references):
        cached = cache.get(_pr_ci_status_cache_key(team_id, reference))
        if cached == _PR_CI_STATUS_UNREADABLE:
            continue
        if isinstance(cached, str):
            resolved[reference] = cached
        else:
            misses_by_repository[reference.repository].append(reference)

    # An installation is granted per repository, so one integration lookup per repository is what
    # bounds the access probes. Repositories that share an installation collapse into one query.
    batches: dict[int, tuple[GitHubIntegration, list[PullRequestRef]]] = {}
    for repository, repository_references in misses_by_repository.items():
        try:
            github = GitHubIntegration.first_for_team_repository(
                team_id, repository, source="signals_pr_ci_status", priority=Priority.NORMAL
            )
        except (GitHubRateLimitError, GitHubEgressBudgetExhausted):
            # The probe never reached GitHub, so nothing was learned about the repository. Same
            # policy as a throttled fetch below: remember nothing and let the next poll ask again.
            logger.info("signals.reports.pr_ci_statuses.lookup_throttled", repository=repository)
            continue
        except Exception:
            logger.warning(
                "signals.reports.pr_ci_statuses.integration_lookup_failed", repository=repository, exc_info=True
            )
            continue
        if github is None:
            # GitHub answered, and no installation reaches the repository. That is stable enough
            # to remember, so the probe does not run again on every load and every poll.
            _remember_unreadable_pr_ci_statuses(team_id, repository_references)
            continue
        _, pending = batches.setdefault(github.integration.id, (github, []))
        pending.extend(repository_references)

    for github, pending in batches.values():
        # One call per batch, cached as it lands, so a failure costs the batches it stopped and
        # not the ones GitHub already answered for. Stop this integration at the first failure:
        # another call would spend the same budget on the same condition.
        batch_size = GitHubIntegration.PR_CI_STATUS_BATCH_SIZE
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            try:
                fetched = github.get_pull_request_ci_statuses(batch)
            except (GitHubRateLimitError, GitHubEgressBudgetExhausted):
                # Expected under load, and the reader loses nothing they had: skip the glyph and
                # let the next request (or the detail view) answer once the limit clears.
                logger.info("signals.reports.pr_ci_statuses.throttled", pr_count=len(batch))
                break
            except Exception:
                logger.warning("signals.reports.pr_ci_statuses.fetch_failed", pr_count=len(batch), exc_info=True)
                break
            for reference, ci_status in fetched.items():
                cache.set(_pr_ci_status_cache_key(team_id, reference), ci_status, timeout=PR_CI_STATUS_CACHE_SECONDS)
                resolved[reference] = ci_status
            # GitHub answered the batch but left this pull request out, so the installation cannot
            # read it (deleted, transferred, or access revoked). That is stable enough to remember.
            _remember_unreadable_pr_ci_statuses(team_id, [ref for ref in batch if ref not in fetched])
    return resolved


def _remember_unreadable_pr_ci_statuses(team_id: int, references: Iterable[PullRequestRef]) -> None:
    """Remember, briefly, that GitHub cannot answer for these pull requests.

    Without this every list load and every poll re-runs the per-repository access probe, and then
    the query, for a pull request that is never going to resolve. The window is short so access
    granted a moment later still takes effect quickly.
    """
    for reference in references:
        cache.set(
            _pr_ci_status_cache_key(team_id, reference),
            _PR_CI_STATUS_UNREADABLE,
            timeout=PR_CI_STATUS_UNREADABLE_CACHE_SECONDS,
        )


def _pr_ci_status_cache_key(team_id: int, reference: PullRequestRef) -> str:
    return f"signals:pr-ci-status:{team_id}:{reference.repository}:{reference.number}"


def rollup_ci_status(references: Collection[PullRequestRef], statuses: Mapping[PullRequestRef, str]) -> str | None:
    """One state for several pull requests. A failure anywhere wins, because it is enough to act on.
    Otherwise None when a pull request has no known state, so a caller does not claim a state it lacks."""
    known = {statuses[ref] for ref in references if ref in statuses}
    if "failing" in known:
        return "failing"
    if not references or any(ref not in statuses for ref in references):
        return None
    if "pending" in known:
        return "pending"
    return "passing" if known == {"passing"} else "none"
