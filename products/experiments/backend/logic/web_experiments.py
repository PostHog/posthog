from collections.abc import Mapping
from typing import Any

from django.db.models import QuerySet
from django.utils.text import slugify

from nanoid import generate

from posthog.event_usage import report_user_action
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.experiments.backend.facade.contracts import WebExperimentWrite
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.models.web_experiment import WebExperiment
from products.feature_flags.backend.facade.api import create_flag, update_flag
from products.feature_flags.backend.facade.filters import replace_variant_distribution


def _with_relations(queryset: QuerySet[WebExperiment]) -> QuerySet[WebExperiment]:
    return queryset.select_related("feature_flag")


def list_page(*, project_id: int, page: PageRequest) -> Page[WebExperiment]:
    # `deleted=False` also drops rows where `deleted` is NULL.
    queryset = WebExperiment.objects.filter(deleted=False, team__project_id=project_id).order_by("-created_at", "-id")
    return select_page(strict_fetch(_with_relations(queryset)), page)


def get(*, project_id: int, web_experiment_id: int) -> WebExperiment | None:
    return _with_relations(WebExperiment.objects.filter(team__project_id=project_id, pk=web_experiment_id)).first()


def list_for_toolbar(*, team_id: int) -> list[WebExperiment]:
    # The root team queryset rewrites a `team_id` keyword filter so that an environment also matches the
    # experiments of its project's root team, where web experiments are stored.
    return list(
        _with_relations(
            WebExperiment.objects.filter(team_id=team_id)
            .exclude(archived=True)
            .exclude(deleted=True)
            .filter(status__in=[Experiment.Status.DRAFT, Experiment.Status.RUNNING])
        ).order_by("-created_at")
    )


def corrected_variants(experiment: WebExperiment) -> dict[str, Any]:
    """
    Returns ALL variants from the feature flag with actual rollout percentages,
    combined with transforms from the experiment variants where available.
    """
    variants_list = experiment.feature_flag.variants

    if not variants_list:
        return experiment.variants or {}

    result_variants = {}
    experiment_variants = experiment.variants or {}

    for variant in variants_list:
        key = variant.get("key")
        rollout_percentage = variant.get("rollout_percentage", 0)
        if key:
            result_variants[key] = {"rollout_percentage": rollout_percentage}

            if key in experiment_variants:
                experiment_data = experiment_variants[key].copy()
                # Remove rollout_percentage from experiment data to avoid conflicts
                experiment_data.pop("rollout_percentage", None)
                result_variants[key].update(experiment_data)

    return result_variants


def _flag_variants(variants: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": key, "rollout_percentage": variant.get("rollout_percentage", 0)} for key, variant in variants.items()
    ]


def _feature_flag_key(experiment_name: str) -> str:
    random_id = generate("1234567890abcdef", 10)
    prefix = experiment_name.replace(" ", "-").lower() + "-web-experiment-feature"
    return slugify(f"{prefix}-{random_id}")


def create(
    *, team: Team, project_id: int, user: User, write: WebExperimentWrite, serializer_context: Mapping[str, Any]
) -> WebExperiment:
    if write.name is None or write.variants is None:
        raise ValueError("A new web experiment needs a name and variants.")
    request = serializer_context["request"]

    filters = {
        "groups": [{"properties": [], "rollout_percentage": 100}],
        "multivariate": {"variants": _flag_variants(write.variants)},
    }
    feature_flag = create_flag(
        {
            "key": _feature_flag_key(write.name),
            "name": f"Feature Flag for Experiment {write.name}",
            "filters": filters,
            "active": False,
            "creation_context": "web_experiments",
        },
        team=team,
        user=user,
        request=request,
    )

    config = get_or_create_team_extension(team, TeamExperimentsConfig)
    stats_config = {"method": config.default_experiment_stats_method or "bayesian"}

    experiment = WebExperiment.objects.create(
        team_id=project_id,
        feature_flag=feature_flag,
        name=write.name,
        description="",
        type="web",
        created_by=user,
        variants=write.variants,
        stats_config=stats_config,
    )

    report_user_action(
        user,
        "experiment created",
        {**experiment.get_analytics_metadata(), "creation_mode": "new"},
        team=team,
        request=request,
    )

    return experiment


def update(
    experiment: WebExperiment,
    *,
    team: Team,
    user: User,
    write: WebExperimentWrite,
    serializer_context: Mapping[str, Any],
) -> WebExperiment:
    if write.variants is not None:
        feature_flag = experiment.feature_flag
        filters = replace_variant_distribution(feature_flag.get_filters(), _flag_variants(write.variants))
        update_flag(feature_flag, {"filters": filters}, team=team, user=user, request=serializer_context["request"])

    for field in write.fields_set:
        setattr(experiment, field, getattr(write, field))
    experiment.save()
    return experiment


def delete(experiment: WebExperiment) -> None:
    experiment.delete()
