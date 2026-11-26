from uuid import UUID

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception

from products.managed_warehouse.backend.facade.feature_flags import MANAGED_WAREHOUSE_ACCESS_FLAGS
from products.managed_warehouse.backend.models import ManagedWarehouseSourceLifecycle

LOGGER = structlog.get_logger(__name__)


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


def data_imports_registration_allowed(organization_id: UUID | str) -> bool | None:
    """Whether the organization has the managed warehouse, the first condition of DuckLake data imports
    registration. Configured background loading decides on its own; otherwise either access flag grants it.

    None when no flag granted access and at least one could not answer, because its evaluation raised or the
    local flag definitions are not loaded. The gate treats None as no; a caller that skips work on no must not.
    """
    organization_id = str(organization_id)
    allowed: bool | None = False
    # Each flag is evaluated on its own, so an error on one flag cannot hide access the other grants.
    for flag in MANAGED_WAREHOUSE_ACCESS_FLAGS:
        try:
            enabled = posthoganalytics.feature_enabled(
                flag,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        except Exception as error:
            LOGGER.warning(
                "Failed to evaluate DuckLake data imports registration feature flag", flag=flag, error=str(error)
            )
            capture_exception(error)
            enabled = None
        if enabled is True:
            allowed = True
            break
        if enabled is None:
            allowed = None

    if background_loading_configured(organization_id):
        allowed = internal_loading_enabled(organization_id)
    return allowed
