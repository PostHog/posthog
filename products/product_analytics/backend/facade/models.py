"""
Model-class wiring for product_analytics.

Re-exports the ``Insight``, ``InsightVariable`` and ``InsightViewed`` model
classes for cross-product consumers under the watched-models allowance
(MODEL_CROSSINGS): dashboards, alerts, exports, sharing and other areas hold
ForeignKeys or M2Ms into ``Insight`` and need ORM semantics (relation
traversal, cascade deletes, queryset-typed access-control filtering, the
view-tracking ``update_or_create``) that a frozen contract cannot express.
Also carries the model-module helper ``generate_insight_filters_hash``, which
takes model instances. The whole model surface (``backend/models/`` and
``backend/migrations/``) stays in the contract-check inputs, so a change to
these classes still runs the full suite.
"""

from products.product_analytics.backend.models.insight import Insight, InsightViewed, generate_insight_filters_hash
from products.product_analytics.backend.models.insight_variable import InsightVariable

__all__ = ["Insight", "InsightVariable", "InsightViewed", "generate_insight_filters_hash"]
