"""Experiment reads for the signals scout harness, which orients its agents on a team's experiments."""

from products.experiments.backend.facade.contracts import ExperimentOrientation, RecentExperiment
from products.experiments.backend.models.experiment import Experiment


def experiment_orientation(*, team_id: int, recent_limit: int) -> ExperimentOrientation:
    """The team's experiment counts and its `recent_limit` most recently modified experiments."""
    # `team=` matches this team only. RootTeamQuerySet rewrites `team_id=` to the parent team when the team has one.
    experiments = Experiment.objects.filter(team=team_id).exclude(deleted=True)
    recent = experiments.order_by("-updated_at").values(
        "id", "name", "archived", "start_date", "end_date", "feature_flag__key", "updated_at"
    )[:recent_limit]
    return ExperimentOrientation(
        total_count=experiments.count(),
        running_count=experiments.filter(archived=False, start_date__isnull=False, end_date__isnull=True).count(),
        recent=tuple(
            RecentExperiment(
                id=row["id"],
                name=row["name"],
                archived=row["archived"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                feature_flag_key=row["feature_flag__key"],
                updated_at=row["updated_at"],
            )
            for row in recent
        ),
    )
