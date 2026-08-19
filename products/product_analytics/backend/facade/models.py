"""
Model-class wiring for product_analytics.

Re-exports the ``Insight`` and ``InsightVariable`` model classes for
cross-product consumers under the watched-models allowance (MODEL_CROSSINGS):
dashboards, alerts, exports, sharing and other areas hold ForeignKeys or M2Ms
into ``Insight`` and need ORM semantics (relation traversal, cascade deletes,
queryset-typed access-control filtering) that a frozen contract cannot
express. The whole model surface (``backend/models/`` and
``backend/migrations/``) stays in the contract-check inputs, so a change to
these classes still runs the full suite.
"""

from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_variable import InsightVariable

__all__ = ["Insight", "InsightVariable"]
