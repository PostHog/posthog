from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.workflows.backend.models import HogFlow, HogFlowOptimization
from products.workflows.backend.services.suggestions_scout import sync_suggestions_scout


def _sync_after_commit(team_id: int) -> None:
    def sync() -> None:
        # Without a person there is nobody to grant the scout's write scope, so this can only switch it off.
        try:
            team = Team.objects.filter(id=team_id).select_related("parent_team").first()
            if team is not None:
                sync_suggestions_scout(team, acting_user=None, may_grant=False)
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
