from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.models import HogFlow, HogFlowOptimization


def _sync_after_commit(team_id: int) -> None:
    def sync() -> None:
        # Deferred: the signals facade it pulls in would otherwise load on every django.setup().
        from products.workflows.backend.services import suggestions_scout  # noqa: PLC0415

        # Without a person there is nobody to grant the scout's write scope, so this can only switch it off.
        try:
            team = Team.objects.filter(id=team_id).select_related("parent_team").first()
            if team is not None:
                suggestions_scout.sync_suggestions_scout(team, acting_user=None, may_grant=False)
        except Exception as error:
            capture_exception(error)

    transaction.on_commit(sync)


@receiver(post_delete, sender=HogFlowOptimization)
def optimization_deleted(sender: type, instance: HogFlowOptimization, **kwargs: object) -> None:
    # Fires for each row a deleted workflow takes with it, in single and bulk deletes alike.
    if instance.enabled:
        _sync_after_commit(instance.team_id)


@receiver(post_save, sender=HogFlow)
def workflow_saved(sender: type, instance: HogFlow, **kwargs: object) -> None:
    # Archiving the last opted-in workflow has to stop the scout as surely as opting it out does.
    if (
        instance.status != HogFlow.State.ACTIVE
        and HogFlowOptimization.objects.unscoped().filter(hog_flow_id=instance.id, enabled=True).exists()
    ):
        _sync_after_commit(instance.team_id)


@receiver(post_save, sender=Cohort)
def cohort_saved(sender: type, instance: Cohort, **kwargs: object) -> None:
    # The cohorts API deletes by setting `deleted`, and undo restores it. Recalculation saves never touch it.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "deleted" not in update_fields:  # type: ignore[operator]
        return
    team_id, cohort_id, deleted = instance.team_id, instance.pk, instance.deleted

    def mark() -> None:
        # Deferred: the recipient list service pulls in HogQL, which would otherwise load on every django.setup().
        from products.workflows.backend.services import recipient_lists  # noqa: PLC0415

        recipient_lists.mark_recipient_list_cohort_deleted(team_id, cohort_id, deleted)

    transaction.on_commit(mark)


@receiver(post_delete, sender=Cohort)
def cohort_deleted(sender: type, instance: Cohort, **kwargs: object) -> None:
    team_id, cohort_id = instance.team_id, instance.pk

    def delete() -> None:
        from products.workflows.backend.services import recipient_lists  # noqa: PLC0415

        recipient_lists.delete_recipient_list_for_cohort(team_id, cohort_id)

    transaction.on_commit(delete)
