"""
Exported constants for endpoints.

Contract-file tier alongside ``contracts.py``: pure values the product's own
presentation and external consumers may import without touching internals.
"""

from products.endpoints.backend.constants import ENDPOINT_NAME_REGEX, ENDPOINTS_LOG_SOURCE

__all__ = ["ENDPOINT_NAME_REGEX", "ENDPOINTS_LOG_SOURCE"]
