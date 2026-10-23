"""Warehouse name validation and the public connection the name resolves to."""

import re
from typing import TypedDict
from uuid import UUID

from django.conf import settings

from rest_framework import status
from rest_framework.response import Response

from . import control_plane

# The Postgres database to connect to is always "ducklake"; the user-chosen warehouse
# name becomes the SNI subdomain (e.g. my-warehouse.dw.us.postwh.com) and the DNS zone
# is selected by the deployment.
MANAGED_WAREHOUSE_DATABASE = "ducklake"

_MANAGED_WAREHOUSE_DOMAINS = {
    "US": "us.postwh.com",
    "EU": "eu.postwh.com",
    "DEV": "dev.postwh.com",
}

# A warehouse name becomes a DNS-1123 label (the connection's SNI subdomain), so it must
# be lowercase alphanumerics and hyphens, starting and ending alphanumeric — no
# underscores. Mirrors duckgres's own org-id constraint.
WAREHOUSE_NAME_MIN_LENGTH = 3

WAREHOUSE_NAME_MAX_LENGTH = 63

WAREHOUSE_NAME_PATTERN = re.compile(r"^[a-z]([a-z0-9-]*[a-z0-9])?$")


class PresentedConnection(TypedDict):
    host: str
    port: int
    database: str
    username: str


def managed_warehouse_domain() -> str:
    deployment = (getattr(settings, "CLOUD_DEPLOYMENT", None) or "").upper()
    return _MANAGED_WAREHOUSE_DOMAINS.get(deployment, "test.local")


def validate_warehouse_name(name: str | None) -> str | None:
    """Return a human-readable error if `name` is not a valid warehouse name, else None."""
    if not name:
        return "database_name is required"
    if not (WAREHOUSE_NAME_MIN_LENGTH <= len(name) <= WAREHOUSE_NAME_MAX_LENGTH):
        return f"Warehouse name must be {WAREHOUSE_NAME_MIN_LENGTH}-{WAREHOUSE_NAME_MAX_LENGTH} characters"
    if not WAREHOUSE_NAME_PATTERN.match(name):
        return (
            "Warehouse name must be a DNS label: lowercase letters, numbers, and hyphens, "
            "starting and ending with a letter or number"
        )
    return None


def _present_connection(raw: dict) -> PresentedConnection:
    """Build the public-facing connection from duckgres's raw status connection.

    duckgres returns the org's chosen warehouse name as `database`; that becomes the SNI
    subdomain of the host, and the database to connect to is always "ducklake".
    """
    warehouse_name = raw.get("database")
    host = f"{warehouse_name}.dw.{managed_warehouse_domain()}" if warehouse_name else raw.get("host", "")
    return PresentedConnection(
        host=host,
        port=getattr(settings, "DUCKGRES_PG_PORT", 5432),
        database=MANAGED_WAREHOUSE_DATABASE,
        username=raw.get("username", "root"),
    )


def check_name(organization_id: UUID | str, name: str | None) -> Response:
    name_error = validate_warehouse_name(name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    return control_plane._request("GET", organization_id, "database-name/check", params={"name": name}, timeout=10)
