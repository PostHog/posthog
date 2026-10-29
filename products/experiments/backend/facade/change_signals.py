from collections.abc import Callable
from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import Signal

from products.experiments.backend.facade.contracts import ExperimentChanged
from products.experiments.backend.models.experiment import Experiment

# Sent with `change=`, an `ExperimentChanged`, after every save and delete of an experiment, so other products react
# to it without importing the experiments model.
experiment_changed = Signal()


def connect_experiment_changed(receiver: Callable[..., object], *, dispatch_uid: str) -> None:
    """``receiver`` gets ``change=``, an ``ExperimentChanged``, after each save and each hard delete of an
    experiment. A soft delete is a save with ``change.deleted`` set.

    The receiver runs synchronously right after the row is written, inside the caller's transaction when there is
    one, like a ``post_save`` receiver. An exception it raises propagates out of ``save()`` or ``delete()``. Work that
    must wait for the commit goes through ``transaction.on_commit``."""
    experiment_changed.connect(receiver, dispatch_uid=dispatch_uid)


def _change(experiment: Experiment, *, created: bool, deleted: bool) -> ExperimentChanged:
    return ExperimentChanged(
        team_id=experiment.team_id,
        experiment_id=experiment.id,
        created=created,
        deleted=deleted,
        name=experiment.name,
        description=experiment.description,
        archived=experiment.archived,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
    )


# Both receivers use `send`, not `send_robust`, so a receiver error propagates out of `save()` or `delete()`, as an
# error in a receiver of the model signal does.
def _notify_experiment_saved(sender: Any, instance: Experiment, created: bool, **kwargs: Any) -> None:
    # The column is nullable, and NULL reads as not deleted.
    change = _change(instance, created=created, deleted=bool(instance.deleted))
    experiment_changed.send(sender=ExperimentChanged, change=change)


def _notify_experiment_deleted(sender: Any, instance: Experiment, **kwargs: Any) -> None:
    experiment_changed.send(sender=ExperimentChanged, change=_change(instance, created=False, deleted=True))


post_save.connect(_notify_experiment_saved, sender=Experiment, dispatch_uid="experiments.experiment_changed.save")
post_delete.connect(_notify_experiment_deleted, sender=Experiment, dispatch_uid="experiments.experiment_changed.delete")
