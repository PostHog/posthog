"""Lookup of the warehouse sources that use a core ``Integration``, for the integrations API."""

from products.warehouse_sources.backend.logic.integration_references import list_sources_using_integration

__all__ = ["list_sources_using_integration"]
