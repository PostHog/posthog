"""Destination health transitions used by warehouse presentation endpoints."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import ExternalDataDestination


def resume_destination(destination: "ExternalDataDestination") -> None:
    # Deferred to keep the email task graph off Django's model import path.
    from products.warehouse_sources.backend.destination_health import resume_destination as _resume_destination

    _resume_destination(destination)


__all__ = ["resume_destination"]
