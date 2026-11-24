"""Web experiments capability: the reads and writes of the web experiments API and the toolbar.

Create and update write the feature flag through the feature flags facade. An exception from that write, such as
the `ValidationError` of Django REST framework when the team is at its flag limit, passes through unchanged.
"""

from collections.abc import Mapping
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.paging import Page, PageRequest

from products.experiments.backend.logic import web_experiments
from products.experiments.backend.models.web_experiment import WebExperiment

from .contracts import WebExperimentConfig, WebExperimentNotFound, WebExperimentWrite


def _to_config(experiment: WebExperiment) -> WebExperimentConfig:
    return WebExperimentConfig(
        id=experiment.id,
        name=experiment.name,
        created_at=experiment.created_at,
        feature_flag_key=experiment.feature_flag.key,
        variants=web_experiments.corrected_variants(experiment),
    )


def list_web_experiments(*, project_id: int, page: PageRequest) -> Page[WebExperimentConfig]:
    """One page of the project's web experiments that are not deleted, newest first."""
    return web_experiments.list_page(project_id=project_id, page=page).map(_to_config)


def get_web_experiment(*, project_id: int, web_experiment_id: int) -> WebExperimentConfig | None:
    """The project's web experiment with the id, also when it is deleted, or None when there is none."""
    experiment = web_experiments.get(project_id=project_id, web_experiment_id=web_experiment_id)
    return None if experiment is None else _to_config(experiment)


def list_toolbar_web_experiments(*, team_id: int) -> list[WebExperimentConfig]:
    """The draft and running web experiments of the team's project that are not archived or deleted, newest first."""
    return [_to_config(experiment) for experiment in web_experiments.list_for_toolbar(team_id=team_id)]


def create_web_experiment(
    *, team: Team, project_id: int, user: User, write: WebExperimentWrite, serializer_context: Mapping[str, Any]
) -> WebExperimentConfig:
    """Create a web experiment in the project, with a new inactive feature flag that splits the variants.

    The flag write and the analytics event read the API request from `serializer_context`.
    """
    return _to_config(
        web_experiments.create(
            team=team, project_id=project_id, user=user, write=write, serializer_context=serializer_context
        )
    )


def update_web_experiment(
    *,
    team: Team,
    user: User,
    web_experiment_id: int,
    write: WebExperimentWrite,
    serializer_context: Mapping[str, Any],
) -> WebExperimentConfig:
    """Set the fields that the write names. New variants also change the variant split of the feature flag."""
    experiment = web_experiments.get(project_id=team.project_id, web_experiment_id=web_experiment_id)
    if experiment is None:
        raise WebExperimentNotFound(web_experiment_id)
    return _to_config(
        web_experiments.update(experiment, team=team, user=user, write=write, serializer_context=serializer_context)
    )


def delete_web_experiment(*, project_id: int, web_experiment_id: int) -> None:
    """Delete the web experiment row. The feature flag stays."""
    experiment = web_experiments.get(project_id=project_id, web_experiment_id=web_experiment_id)
    if experiment is None:
        raise WebExperimentNotFound(web_experiment_id)
    web_experiments.delete(experiment)
