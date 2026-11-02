"""Create a repository's trigger label on GitHub, so people can pick it on a pull request.

GitHub's label picker only offers labels that exist in the repository. In label mode, a repository
without the trigger label gets no reviews until somebody creates it by hand.
"""

from __future__ import annotations

from django.db import router

import structlog
from celery import shared_task

from products.stamphog.backend.facade.enums import ReviewMode
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.models import StamphogRepoConfig

logger = structlog.get_logger(__name__)

TRIGGER_LABEL_COLOR = "f54e00"
TRIGGER_LABEL_DESCRIPTION = "Ask Stamphog to review this pull request"


@shared_task(ignore_result=True)
def create_trigger_label(team_id: int, config_id: str) -> None:
    """Create the trigger label of an enabled label-mode repository, if GitHub lets the app do it."""
    # Writer pin: the task runs right after the commit that enabled the row, and a lagged replica
    # can still show it disabled or missing.
    config = (
        StamphogRepoConfig.objects.for_team(team_id)
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(id=config_id, enabled=True, review_mode=ReviewMode.LABEL)
        .exclude(installation_id="")
        .first()
    )
    if config is None:
        return
    # Best-effort: without the label, somebody creates it by hand, so no failure here may surface.
    try:
        StamphogGitHubClient(config.installation_id).create_label(
            config.repository,
            config.trigger_label,
            color=TRIGGER_LABEL_COLOR,
            description=TRIGGER_LABEL_DESCRIPTION,
        )
    except Exception:
        logger.warning(
            "stamphog_trigger_label_create_failed",
            repository=config.repository,
            label=config.trigger_label,
            exc_info=True,
        )
