from typing import TYPE_CHECKING

from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from posthog.models import Team

from products.authz.backend.facade.synchronization import (
    invalidate_authorization_session,
    schedule_organization_sync,
    synchronization_enabled,
)

if TYPE_CHECKING:
    from .models.external_data_source import ExternalDataSource
    from .models.table import DataWarehouseTable


@receiver(pre_save, sender="warehouse_sources.DataWarehouseTable")
@receiver(pre_save, sender="warehouse_sources.ExternalDataSource")
@receiver(pre_delete, sender="warehouse_sources.DataWarehouseTable")
@receiver(pre_delete, sender="warehouse_sources.ExternalDataSource")
def remember_authorization_state(
    sender: type[Model], instance: "DataWarehouseTable | ExternalDataSource", using: str, **kwargs: object
) -> None:
    if not synchronization_enabled():
        return
    fields = ["team_id", "created_by_id", "deleted"]
    if sender._meta.model_name == "datawarehousetable":
        fields.append("external_data_source_id")
    # Read the stored tenant so a move revokes the old organization's relationships too.
    old = sender._base_manager.using(using).filter(pk=instance.pk).values(*fields, "team__organization_id").first()
    instance.__dict__["_authz_old_organization_id"] = old["team__organization_id"] if old else None
    # Ingestion updates table metadata frequently; only authorization inputs require reconciliation.
    instance.__dict__["_authz_warehouse_changed"] = old is None or any(
        old[field] != getattr(instance, field) for field in fields
    )


@receiver(post_save, sender="warehouse_sources.DataWarehouseTable")
@receiver(post_save, sender="warehouse_sources.ExternalDataSource")
@receiver(post_delete, sender="warehouse_sources.DataWarehouseTable")
@receiver(post_delete, sender="warehouse_sources.ExternalDataSource")
def synchronize_warehouse(
    sender: type[Model],
    instance: "DataWarehouseTable | ExternalDataSource",
    using: str,
    raw: bool = False,
    **kwargs: object,
) -> None:
    invalidate_authorization_session()
    if raw or not synchronization_enabled():
        return
    if kwargs.get("signal") is post_save and not instance.__dict__.get("_authz_warehouse_changed", True):
        return
    organization_id = (
        Team.objects.using(using).filter(id=instance.team_id).values_list("organization_id", flat=True).first()
    )
    for id in {organization_id, instance.__dict__.get("_authz_old_organization_id")}:
        if id is not None:
            schedule_organization_sync(id, using=using)
