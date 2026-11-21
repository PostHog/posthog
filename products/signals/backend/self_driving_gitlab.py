from uuid import UUID

import structlog

from posthog.integrations import IntegrationRecord
from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.repo_selection import (
    gitlab_project_for_repository,
    list_team_connected_repositories,
    team_gitlab_project_paths,
)

logger = structlog.get_logger(__name__)

SELF_DRIVING_GITLAB_FLAG = "self-driving-gitlab"


def self_driving_gitlab_enabled(team_id: int) -> bool:
    try:
        organization_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
        return (
            feature_enabled_or_false(
                SELF_DRIVING_GITLAB_FLAG,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                send_feature_flag_events=False,
                only_evaluate_locally=True,
            )
            is True
        )
    except Exception:
        logger.exception("signals.self_driving_gitlab.flag_check_failed", team_id=team_id)
        return False


def self_driving_gitlab_candidates(team_id: int) -> list[str]:
    """The GitLab project paths repository selection may pick, empty while the flag is off."""
    if not self_driving_gitlab_enabled(team_id):
        return []
    return team_gitlab_project_paths(team_id)


def self_driving_gitlab_project(team_id: int, repository: str | None) -> IntegrationRecord | None:
    """The GitLab connection a Self-driving task on ``repository`` runs through, or None to use GitHub.

    GitHub wins when the team's installation reaches the same path, so a team that connects GitLab
    keeps every repository GitHub already serves.
    """
    if not repository or not self_driving_gitlab_enabled(team_id):
        return None
    project = gitlab_project_for_repository(team_id, repository)
    if project is None or repository.strip().lower() in list_team_connected_repositories(team_id):
        return None
    return project


def gitlab_run_is_free(team_id: int, task_id: UUID) -> bool:
    """Whether a run is free of charge because its task works on a GitLab project.

    The spend is still recorded, but marked exempt. The daily report limit and the org quota gate
    still apply, but exempt spend does not count toward the paid quota. Delete this helper to start
    charging for GitLab runs.
    """
    return tasks_facade.get_task_repository_integration_id(task_id=task_id, team_id=team_id) is not None
