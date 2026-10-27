from collections.abc import Callable
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import Signal

if TYPE_CHECKING:
    from products.experiments.backend.models.experiment import Experiment

# Sent with `team_id=` and `experiment_id=` after a launch saves, so other products react to it
# without the experiments product importing them.
experiment_launched = Signal()


def connect_experiment_launched(receiver: Callable[..., object], *, dispatch_uid: str) -> None:
    """``receiver`` gets ``team_id=`` and ``experiment_id=`` once a launch saves. A receiver that
    raises is logged and never fails the launch."""
    experiment_launched.connect(receiver, dispatch_uid=dispatch_uid)


def connect_source_experiment_changes(receiver: Callable[..., object], *, flag_prefix: str, dispatch_uid: str) -> None:
    def changed(sender: object, instance: "Experiment", using: str, **kwargs: object) -> None:
        if not instance.feature_flag.key.startswith(flag_prefix):
            return
        team_id, experiment_id = instance.team_id, instance.pk
        transaction.on_commit(lambda: receiver(team_id=team_id, experiment_id=experiment_id), using=using, robust=True)

    post_save.connect(changed, sender="experiments.Experiment", dispatch_uid=dispatch_uid, weak=False)
