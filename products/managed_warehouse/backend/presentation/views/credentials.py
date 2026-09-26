"""Rotation of the warehouse root password."""

from uuid import UUID

import structlog
from rest_framework import status
from rest_framework.response import Response

from . import control_plane

logger = structlog.get_logger(__name__)


def reset_password(organization_id: UUID | str, *, triggered_by: str) -> Response:
    resp = control_plane._request("POST", organization_id, "/reset-password")
    if status.is_success(resp.status_code):
        logger.info(
            "managed_warehouse_action",
            action="reset_password",
            triggered_by=triggered_by,
            organization_id=str(organization_id),
        )
    if status.is_success(resp.status_code) and isinstance(resp.data, dict) and resp.data.get("password"):
        try:
            _update_direct_connection_password(organization_id, resp.data["password"])
        except Exception:
            logger.exception("Failed to update managed warehouse stored password", organization_id=str(organization_id))
            return Response(
                {"error": "The password was rotated but could not be saved. Retry the password reset."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    return resp


def _update_direct_connection_password(organization_id: UUID | str, password: str) -> None:
    """Sync the rotated root password into the server row and query connections."""
    from products.managed_warehouse.backend.facade.connection import (
        update_managed_warehouse_root_password,  # noqa: PLC0415
    )

    update_managed_warehouse_root_password(organization_id=organization_id, password=password)
