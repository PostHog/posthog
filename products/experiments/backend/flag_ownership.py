"""The guards that run when an experiment takes its feature flag on or lets it go.

A soft delete of the last live experiment on a flag releases the flag, and a restore adopts it
again. Both change which product owns the flag, which decides which approval policies cover it
and which other products may use it, so both answer to the checks in feature_flags' `ownership`
module.

These live outside `experiment_service` because the experiment API is not the only writer. The
file system deletes and restores an experiment through its own path, which saves `deleted`
directly, and that path calls these as its pre-delete and pre-restore hooks.
"""

from rest_framework.exceptions import ValidationError

from products.feature_flags.backend.ownership import (
    FLAG_OWNER_EXPERIMENT,
    assert_flag_available_for,
    assert_flag_releasable_by,
    flag_owner_kind,
    flag_owner_label,
)

from .models.experiment import Experiment


def _other_owning_experiments(experiment: Experiment):
    """The live experiments that hold this flag apart from this one.

    Reads through `live_objects` rather than `live_experiments_for_flag`, because the question
    here is who owns the flag and the flag ownership table reads that manager. The two differ on
    an experiment whose `deleted` is null: the manager counts it as an owner, and the helper's
    `deleted=False` does not. Using the helper would refuse a deletion that releases nothing.
    """
    return Experiment.live_objects.filter(feature_flag_id=experiment.feature_flag_id).exclude(pk=experiment.pk)


def assert_experiment_deletable(experiment: Experiment) -> None:
    """Refuse a soft delete that would leave the flag less governed than it is now.

    Only the delete that takes the last live experiment off the flag releases it. While another
    experiment still holds the flag, the owner does not change and nothing is checked.
    """
    if _other_owning_experiments(experiment).exists():
        return
    assert_flag_releasable_by(experiment.feature_flag, product=FLAG_OWNER_EXPERIMENT)


def assert_experiment_restorable(experiment: Experiment) -> None:
    """Refuse a restore that the flag can no longer support.

    A deleted experiment owns nothing, so the restore is an adoption and carries every risk an
    adoption carries: another product may hold the flag by now, and the move back into the
    experiment family may reduce the review the flag needs.
    """
    feature_flag = experiment.feature_flag
    if feature_flag.deleted:
        raise ValidationError(
            "Cannot restore experiment: the linked feature flag has been deleted. "
            "Restore the feature flag first, then restore the experiment."
        )
    owner = flag_owner_kind(feature_flag)
    if owner is not None and owner != FLAG_OWNER_EXPERIMENT:
        raise ValidationError(
            f"Cannot restore experiment: its feature flag {feature_flag.key} now belongs to "
            f"{flag_owner_label(owner)}. Unlink the flag there first, then restore the experiment."
        )
    assert_flag_available_for(feature_flag, product=FLAG_OWNER_EXPERIMENT)
