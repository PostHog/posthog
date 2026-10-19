"""Links into the visual review app for PR comments, check runs and Slack messages.

These links outlive the message that carries them, but `repo_full_name` changes when GitHub renames or transfers
the repo. So a posted link names the repo and the run by id. The app forwards each id path to its owner/name page.
"""

from __future__ import annotations

from django.conf import settings

from ..models import Repo, Run, RunSnapshot


def _app_url(repo: Repo) -> str:
    return f"{settings.SITE_URL}/project/{repo.team_id}/visual-review"


def repo_url(repo: Repo) -> str:
    return f"{_app_url(repo)}/repos/{repo.id}"


def run_url(run: Run, repo: Repo) -> str:
    return f"{_app_url(repo)}/runs/{run.id}"


def snapshot_url(run: Run, repo: Repo, snapshot: RunSnapshot) -> str:
    """Deep link straight to a single snapshot on the run page."""
    return f"{run_url(run, repo)}#snapshot={snapshot.id}"
