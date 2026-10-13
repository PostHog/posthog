"""Links into the visual review app for PR comments, check runs and Slack messages.

The app names a repo by its owner/name path, as GitHub does, so a link reads the same as the repo it points at.
"""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings

from ..models import Repo, Run, RunSnapshot


def repo_url(repo: Repo) -> str:
    owner, _, name = repo.repo_full_name.partition("/")
    return (
        f"{settings.SITE_URL}/project/{repo.team_id}/visual-review/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
    )


def run_url(run: Run, repo: Repo) -> str:
    return f"{repo_url(repo)}/runs/{run.id}"


def snapshot_url(run: Run, repo: Repo, snapshot: RunSnapshot) -> str:
    """Deep link straight to a single snapshot on the run page."""
    return f"{run_url(run, repo)}#snapshot={snapshot.id}"
