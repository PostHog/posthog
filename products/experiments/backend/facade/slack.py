"""Experiment reads for the Slack app, which unfurls links to experiments."""

from products.experiments.backend.facade.contracts import ExperimentUnfurl, ExperimentUnfurlVariant
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.config import ConfigFormatError


def get_experiment_unfurl(*, team_id: int, experiment_id: int) -> ExperimentUnfurl | None:
    """What a link preview shows for an experiment of the team. None when the team has none with this id, or it is deleted."""
    experiment = (
        Experiment.objects.filter(team_id=team_id, pk=experiment_id, deleted=False)
        .select_related("feature_flag")
        .first()
    )
    if experiment is None:
        return None
    try:
        variants = experiment.feature_flag.variants
    except ConfigFormatError:
        variants = []
    return ExperimentUnfurl(
        id=experiment.id,
        created_by_id=experiment.created_by_id,
        name=experiment.name,
        description=experiment.description,
        status=experiment.status_label,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        updated_at=experiment.updated_at,
        primary_metric_name=_first_metric_name(experiment.metrics),
        variants=tuple(
            ExperimentUnfurlVariant(key=variant["key"], rollout_percentage=variant["rollout_percentage"])
            for variant in variants
        ),
    )


def _first_metric_name(metrics: object) -> str | None:
    first = metrics[0] if isinstance(metrics, list) and metrics else None
    name = first.get("name") if isinstance(first, dict) else None
    return name if isinstance(name, str) and name else None
