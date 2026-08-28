"""
Model-class wiring for product_analytics.

Re-exports the ``Insight`` and ``InsightVariable`` model classes for consumers under the
watched-models allowance (MODEL_CROSSINGS), together with the model-module helper
``generate_insight_filters_hash``, which takes model instances. Consumers are moving behind
facade functions; see products/architecture.md § Wiring couplings for what a consumer may do
with a crossing class while they do. ``InsightVariable`` has no consumer left outside the
product, but the SQL-variables ``ModelViewSet`` in ``presentation/`` still needs the class, and
presentation may only reach internals through the facade. The whole model surface
(``backend/models/`` and ``backend/migrations/``) stays in the contract-check inputs, so a change
to these classes still runs the full suite.
"""

from products.product_analytics.backend.models.insight import Insight, generate_insight_filters_hash
from products.product_analytics.backend.models.insight_variable import InsightVariable

__all__ = ["Insight", "InsightVariable", "generate_insight_filters_hash"]
