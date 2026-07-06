"""
Model-class wiring for endpoints.

Light re-exports of the model classes cross-product object-consumers need
(demo-data generation, HogQL system-table test fixtures). Prefer the
contract-returning functions in ``facade.api`` for data access; import from
here only when the consumer genuinely needs the model class itself.
"""

from products.endpoints.backend.models import Endpoint, EndpointVersion

__all__ = ["Endpoint", "EndpointVersion"]
