from uuid import UUID

from products.managed_warehouse.backend.models import ManagedWarehouseSourceLifecycle


def is_internal_warehouse(organization_id: UUID | str) -> bool:
    return ManagedWarehouseSourceLifecycle.objects.filter(organization_id=organization_id, internal_only=True).exists()


def internal_loading_enabled(organization_id: UUID | str) -> bool:
    return ManagedWarehouseSourceLifecycle.objects.filter(
        organization_id=organization_id,
        internal_only=True,
        desired_active=True,
        organization__is_pending_deletion=False,
    ).exists()
