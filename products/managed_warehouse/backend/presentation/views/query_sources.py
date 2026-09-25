"""Lifecycle of the managed SQL-editor query sources that point at the warehouse."""

from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)


def _active_managed_source_generation(organization_id: UUID | str) -> int | None:
    from products.managed_warehouse.backend.facade.connection import (  # noqa: PLC0415
        get_active_managed_warehouse_source_generation,
    )

    return get_active_managed_warehouse_source_generation(organization_id=organization_id)


def _managed_source_generation(organization_id: UUID | str) -> int:
    from products.managed_warehouse.backend.facade.connection import (  # noqa: PLC0415
        get_managed_warehouse_source_generation,
    )

    return get_managed_warehouse_source_generation(organization_id=organization_id)


def _activate_managed_source_lifecycle(
    organization_id: UUID | str,
    *,
    expected_generation: int,
) -> int | None:
    from products.managed_warehouse.backend.facade.connection import (  # noqa: PLC0415
        activate_managed_warehouse_source_lifecycle,
    )

    return activate_managed_warehouse_source_lifecycle(
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def _deactivate_managed_source_lifecycle(
    organization_id: UUID | str,
    *,
    expected_generation: int,
) -> int | None:
    from products.managed_warehouse.backend.facade.connection import (  # noqa: PLC0415
        deactivate_managed_warehouse_source_lifecycle,
    )

    return deactivate_managed_warehouse_source_lifecycle(
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def _ensure_direct_source(team_id: int, organization_id: UUID | str, source_generation: int) -> None:
    try:
        from products.managed_warehouse.backend.facade.connection import (  # noqa: PLC0415
            ensure_managed_warehouse_direct_source,
        )

        ensure_managed_warehouse_direct_source(
            team_id=team_id,
            organization_id=organization_id,
            expected_generation=source_generation,
        )
    except Exception:
        logger.exception("Failed to register managed warehouse query source", team_id=team_id)
        try:
            from products.data_warehouse.backend.facade.api import (  # noqa: PLC0415
                schedule_managed_warehouse_direct_source_ensure,
            )

            schedule_managed_warehouse_direct_source_ensure(
                team_id=team_id,
                organization_id=organization_id,
                expected_generation=source_generation,
            )
        except Exception:
            logger.exception("Failed to schedule managed warehouse query source recovery", team_id=team_id)


def _remove_direct_connection_sources(organization_id: UUID | str, expected_generation: int) -> None:
    """Soft-delete the org's auto-created Postgres query connections after deprovisioning."""
    from products.managed_warehouse.backend.facade.connection import (
        soft_delete_managed_warehouse_sources,  # noqa: PLC0415
    )

    soft_delete_managed_warehouse_sources(
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def _schedule_remove_direct_connection_sources(organization_id: UUID | str, expected_generation: int) -> None:
    """Queue the retrying cleanup task when the inline soft-delete failed."""
    # Keep the Celery task stack off this adapter's import path.
    from products.data_warehouse.backend.facade.api import (  # noqa: PLC0415
        schedule_soft_delete_managed_warehouse_sources,
    )

    schedule_soft_delete_managed_warehouse_sources(
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def ensure_direct_connection_tables(team_id: int, organization_id: UUID | str) -> None:
    """Queue discovery of the team's managed-warehouse tables for the SQL editor.

    Called from the warehouse-status read once the warehouse is `ready`. Repeated requests are
    coalesced for a short interval, while later runs re-introspect the live catalog so newly created
    project tables appear automatically.
    """
    # Keep the Celery and data-warehouse task stack off this adapter's import path.
    from products.data_warehouse.backend.facade.api import schedule_managed_warehouse_tables_reconcile  # noqa: PLC0415

    try:
        schedule_managed_warehouse_tables_reconcile(team_id=team_id, organization_id=organization_id)
    except Exception:
        logger.exception(
            "Failed to schedule managed warehouse direct connection table reconciliation",
            organization_id=str(organization_id),
            team_id=team_id,
        )
