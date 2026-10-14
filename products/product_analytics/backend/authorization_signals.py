from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from posthog.models import Team

from products.authz.backend.facade.synchronization import (
    invalidate_authorization_session,
    schedule_organization_sync,
    synchronization_enabled,
)
from products.product_analytics.backend.models.insight import Insight


@receiver(pre_save, sender=Insight)
@receiver(pre_delete, sender=Insight)
def remember_organization(sender: type[Insight], instance: Insight, using: str, **kwargs: object) -> None:
    if synchronization_enabled():
        instance.__dict__["_authz_old_organization_id"] = (
            Insight.objects_including_soft_deleted.using(using)
            .filter(pk=instance.pk)
            .values_list("team__organization_id", flat=True)
            .first()
        )


@receiver(post_save, sender=Insight)
@receiver(post_delete, sender=Insight)
def synchronize_insight(
    sender: type[Model], instance: Insight, using: str, raw: bool = False, **kwargs: object
) -> None:
    invalidate_authorization_session()
    if raw or not synchronization_enabled():
        return
    organization_id = (
        Team.objects.using(using).filter(id=instance.team_id).values_list("organization_id", flat=True).first()
    )
    for id in {organization_id, instance.__dict__.get("_authz_old_organization_id")}:
        if id is not None:
            schedule_organization_sync(id, using=using)
