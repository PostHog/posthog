from typing import Any

from posthog.models.activity_logging.activity_log import AuditableScope, Change, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.models.web_experiment import WebExperiment

# Kept in sync with DERIVED_RUNNING_TIME_KEYS in
# products/experiments/frontend/components/activity-descriptions/experimentChangeDescription.tsx.
DERIVED_RUNNING_TIME_KEYS = ("recommended_running_time", "recommended_sample_size")


def _without_derived_running_time_keys(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key not in DERIVED_RUNNING_TIME_KEYS}


def _is_derived_running_time_drift(change: Change) -> bool:
    if change.field != "running_time_calculation":
        return False
    # The validator lets falsy non-dict values (for example []) through, and those are
    # never calculator drift, so a transition involving one must stay logged.
    for value in (change.before, change.after):
        if value is not None and not isinstance(value, dict):
            return False
    return _without_derived_running_time_keys(change.before) == _without_derived_running_time_keys(change.after)


@mutable_receiver(model_activity_signal, sender=Experiment)
@mutable_receiver(model_activity_signal, sender=WebExperiment)
def handle_experiment_change(
    sender: type[Experiment],
    scope: AuditableScope,
    before_update: Experiment | None,
    after_update: Experiment,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    # WebExperiment is a proxy model - normalize scope to "Experiment" for consistent activity logs
    scope = "Experiment"
    is_web_experiment = after_update.type == Experiment.ExperimentType.WEB

    if before_update and after_update:
        before_deleted = getattr(before_update, "deleted", None)
        after_deleted = getattr(after_update, "deleted", None)
        if before_deleted is not None and after_deleted is not None and before_deleted != after_deleted:
            activity = "restored" if after_deleted is False else "deleted"
        # Clearing the start date returns the experiment to draft, which is what a reset does,
        # whichever endpoint performed the write.
        elif activity == "updated" and before_update.start_date is not None and after_update.start_date is None:
            activity = "reset"

    changes = changes_between(scope, previous=before_update, current=after_update)

    if is_web_experiment:
        # Web experiments don't use parameters (a product experiment field), but it can
        # get cleared to null during updates, producing a noisy diff
        changes = [change for change in changes if change.field != "parameters"]

    # Opening the calculator re-saves the recomputed outputs, so they drift as exposure data
    # changes. A change earns a log entry only when a calculator input was edited.
    # log_activity drops an "updated" activity whose changes end up empty, so a pure-drift
    # save produces no row at all.
    changes = [change for change in changes if not _is_derived_running_time_drift(change)]

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(changes=changes, name=after_update.name),
    )


# Precomputation is managed by PostHog (the auto-enrollment job and staff tooling) and has no
# control in the settings UI, so its changes stay out of the customer's audit trail.
PRECOMPUTATION_FIELDS = frozenset({"experiment_precomputation_enabled", "precomputation_enabled_set_by"})


@mutable_receiver(model_activity_signal, sender=TeamExperimentsConfig)
def handle_team_experiments_config_change(
    sender: type[TeamExperimentsConfig],
    scope: AuditableScope,
    before_update: TeamExperimentsConfig | None,
    after_update: TeamExperimentsConfig,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    if activity == "deleted":
        return

    # The row is created with defaults the first time anything reads the config, which is no
    # decision a person made. The Django admin can also create it with non-default values in
    # one save, so a new row is compared against the defaults instead of being skipped.
    previous = before_update if before_update is not None else TeamExperimentsConfig(team=after_update.team)
    changes = [
        change
        for change in changes_between("Team", previous=previous, current=after_update)
        if change.field not in PRECOMPUTATION_FIELDS
    ]

    # Logged under the Team scope, with the team as the item, so the change sits next to the
    # other project settings in the activity log and the team describer renders it.
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.team_id,
        scope="Team",
        activity="updated",
        detail=Detail(changes=changes, name=after_update.team.name),
    )
