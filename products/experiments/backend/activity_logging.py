from typing import Any

from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.web_experiment import WebExperiment


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

    changes = changes_between(scope, previous=before_update, current=after_update)

    if is_web_experiment:
        # Web experiments don't use parameters (a product experiment field), but it can
        # get cleared to null during updates, producing a noisy diff
        changes = [change for change in changes if change.field != "parameters"]

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
