"""Wiring for the endpoints side of the data_modeling_ops internal API.

Core URL routing imports the viewset from here rather than reaching into presentation
modules. Only imported by posthog/urls.py (request time), so the DRF dependencies stay
off the ``django.setup()`` path.
"""

from products.endpoints.backend.presentation.views.internal_ops import (
    InternalEndpointsOpsFleetViewSet,
    InternalEndpointsOpsViewSet,
)

__all__ = ["InternalEndpointsOpsFleetViewSet", "InternalEndpointsOpsViewSet"]
