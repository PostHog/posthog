"""The setup context: facts about a project that decide how to configure a new experiment."""

from posthog.models.team.team import Team

from products.experiments.backend import setup_context
from products.experiments.backend.facade.contracts import ExperimentSetupContext, ListAccess, SetupContextInputs
from products.experiments.backend.logic.list_access import visible_experiments, visible_saved_metrics


def build_setup_context(
    *,
    team: Team,
    inputs: SetupContextInputs,
    experiment_access: ListAccess | None,
    saved_metric_access: ListAccess | None,
) -> ExperimentSetupContext:
    """Every section of the setup context. The sections that list experiments and shared metrics show only those
    that the access lets the viewer see. See `setup_context.build_setup_context`."""
    return setup_context.build_setup_context(
        team=team,
        inputs=inputs,
        experiments=visible_experiments(team.pk, experiment_access),
        saved_metrics=visible_saved_metrics(team.pk, saved_metric_access),
    )
