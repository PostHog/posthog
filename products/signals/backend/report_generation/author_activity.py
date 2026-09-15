"""Whether a commit author still works on a repository, for reviewer routing.

Commit authorship outlives a person, so blame evidence alone can name a reviewer who left.
The area-activity cache (``repo_activity``) answers the same question inside its own 90-day
window; this module covers the rest of the year by asking GitHub for the author's last commit
anywhere in the repository. A verdict is cached, and an author GitHub cannot speak for is kept,
so a failed lookup never removes a candidate.
"""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.cache import cache
from django.utils import timezone

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import GitHubIntegration

from products.signals.backend.report_generation.repo_activity import days_since

logger = logging.getLogger(__name__)

# A commit author who has not touched the repository within this window is treated as gone,
# not as a quiet owner. Set well above the 90-day area-activity window so that an author who
# merely moved to another part of the repository still counts.
AUTHOR_ACTIVITY_WINDOW_DAYS = 365
# A verdict this old is still good: the window is a year, so a day's drift cannot flip one.
# It keeps a retried or repeated report off GitHub's rate-limit budget.
AUTHOR_ACTIVITY_CACHE_TTL_SECONDS = 60 * 60 * 24
# GitHub calls run in parallel, bounded the same way the commit-author lookups are.
MAX_PROBE_WORKERS = 5


def _cache_key(repository: str, login: str) -> str:
    return f"signals:author_inactive:{repository}:{login}"


def without_inactive_authors(
    github: GitHubIntegration,
    repository: str,
    login_weights: Counter[str],
    *,
    proven_active: set[str],
) -> Counter[str]:
    """``login_weights`` without the authors who stopped committing to ``repository``.

    ``proven_active`` names the logins a caller already knows are current, so they cost no
    lookup. A stored verdict answers for the rest before GitHub is asked.
    """
    keys = {login: _cache_key(repository, login) for login in login_weights if login not in proven_active}
    if not keys:
        return login_weights

    cached = cache.get_many(list(keys.values()))
    inactive = {login for login, key in keys.items() if cached.get(key) is True}
    unknown = [login for login, key in keys.items() if key not in cached]
    if unknown:
        inactive |= _probe_inactive_authors(github, repository, unknown)

    if not inactive:
        return login_weights
    logger.info("Dropped %d inactive commit author(s) for %s", len(inactive), repository)
    return Counter({login: weight for login, weight in login_weights.items() if login not in inactive})


def _probe_inactive_authors(github: GitHubIntegration, repository: str, logins: list[str]) -> set[str]:
    """Which of ``logins`` GitHub reports as having stopped committing to ``repository``.

    An author GitHub cannot speak for — a failed probe, a throttled one, or an account with no
    attributed commit on the default branch — is left out, because a probe that did not answer
    must not remove a candidate. Each answer is cached, so a retried report does not re-ask.
    """
    now = timezone.now()
    inactive: set[str] = set()
    with ThreadPoolExecutor(max_workers=min(len(logins), MAX_PROBE_WORKERS)) as pool:
        future_to_login = {pool.submit(github.get_author_last_commit, repository, login): login for login in logins}
        for future in as_completed(future_to_login):
            login = future_to_login[future]
            try:
                last_commit = future.result()
            except GitHubRateLimitError:
                logger.info("GitHub rate limited during author activity probe for %s", repository)
                continue
            except Exception:
                logger.warning("Author activity probe failed for %s", repository, exc_info=True)
                continue
            if last_commit is None or last_commit.last_commit_at is None:
                continue
            is_inactive = days_since(last_commit.last_commit_at, now) > AUTHOR_ACTIVITY_WINDOW_DAYS
            cache.set(_cache_key(repository, login), is_inactive, AUTHOR_ACTIVITY_CACHE_TTL_SECONDS)
            if is_inactive:
                inactive.add(login)
    return inactive
