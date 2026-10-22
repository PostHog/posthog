from uuid import UUID

from products.managed_warehouse.backend.models import ManagedWarehouseSourceLifecycle


def is_internal_warehouse(organization_id: UUID | str) -> bool:
    return ManagedWarehouseSourceLifecycle.objects.filter(organization_id=organization_id, internal_only=True).exists()


def internal_loading_enabled(organization_id: UUID | str) -> bool:
    return ManagedWarehouseSourceLifecycle.objects.filter(
        organization_id=organization_id,
        background_loading_enabled=True,
        desired_active=True,
        organization__is_pending_deletion=False,
    ).exists()


def background_loading_configured(organization_id: UUID | str) -> bool:
    return ManagedWarehouseSourceLifecycle.objects.filter(
        organization_id=organization_id, background_loading_enabled=True
    ).exists()


def enable_customer_warehouse_access(organization_id: UUID | str, *, trino_enabled: bool) -> bool:
    if not trino_enabled:
        return False
    lifecycle = (
        ManagedWarehouseSourceLifecycle.objects.filter(organization_id=organization_id, internal_only=True)
        .only("generation", "desired_active")
        .first()
    )
    if lifecycle is None:
        return True
    if not lifecycle.desired_active or lifecycle.generation == 0:
        return False
    promoted = ManagedWarehouseSourceLifecycle.objects.filter(
        organization_id=organization_id,
        generation=lifecycle.generation,
        internal_only=True,
        desired_active=True,
        organization__is_pending_deletion=False,
        organization__duckgres_server__isnull=False,
    ).update(internal_only=False)
    return bool(promoted) or not is_internal_warehouse(organization_id)
