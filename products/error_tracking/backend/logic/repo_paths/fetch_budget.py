"""Budget for git fetches that list repository files.

Git talks to the git host directly and not through the ``requests`` transport in
``posthog.egress``, so this module registers its own limiter domain. GitHub and GitLab publish no
limit for git fetches, so the defaults are operator ceilings on how often one budget owner is
fetched. Raise them in settings once real traffic is measured.

The budget owner is the credential's owner in the git host's own id space: the GitHub App
installation, or the GitLab project whose access token is used.
"""

from typing import Literal

from posthog.dataclasses import frozen
from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

GIT_FETCH_DOMAIN = "error_tracking_git_fetch"
_SOURCE = "error_tracking_repo_paths"

# The default reserve applies: release jobs run on BATCH, and a person who connects a GitLab
# project waits on a NORMAL probe, so the probe still goes through when release jobs fill the window.
register_policy(
    GIT_FETCH_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="ERROR_TRACKING_GIT_FETCH_PER_MINUTE_BUDGET",
        per_minute_default=20,
        hourly_setting="ERROR_TRACKING_GIT_FETCH_HOURLY_BUDGET",
        hourly_default=120,
    ),
)


@frozen
class GitFetchBudgetOwner:
    provider: Literal["github", "gitlab"]
    # A GitHub App installation id, or "{hostname}/{project_id}" for a GitLab project.
    owner_id: str

    def limiter_key(self) -> str:
        return f"{GIT_FETCH_DOMAIN}:{self.provider}:{self.owner_id}"


def consume_git_fetch_budget(owner: GitFetchBudgetOwner, *, priority: Priority) -> bool:
    """Reserve one git fetch for ``owner``. False means the budget is spent, so defer the fetch."""
    return get_outbound_rate_limiter().consume_sync(owner.limiter_key(), priority=priority, source=_SOURCE)
