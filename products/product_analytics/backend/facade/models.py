"""
Model-class wiring for product_analytics.

Re-exports the ``Insight`` and ``InsightVariable`` model classes for consumers under the
watched-models allowance (MODEL_CROSSINGS), together with helpers that take model instances or
querysets. Consumers are moving behind facade functions; see products/architecture.md § Wiring
couplings for what a consumer may do with a crossing class while they do. ``InsightVariable`` has
no consumer left outside the product, but the SQL-variables ``ModelViewSet`` in ``presentation/``
still needs the class, and presentation may only reach internals through the facade. The whole
model surface (``backend/models/`` and ``backend/migrations/``) stays in the contract-check
inputs, so a change to these classes still runs the full suite.
"""

from django.db.models import QuerySet

from products.product_analytics.backend.models.insight import Insight, generate_insight_filters_hash
from products.product_analytics.backend.models.insight_variable import InsightVariable


def resolve_insight_by_id_or_short_id(queryset: QuerySet[Insight], reference: str | int) -> Insight | None:
    """Resolve an insight reference, preferring its numeric primary key when ambiguous."""
    lookup_value = str(reference).strip()
    if lookup_value.isdigit():
        insight = queryset.filter(pk=int(lookup_value)).first()
        if insight is not None:
            return insight
    return queryset.filter(short_id=lookup_value).first()


__all__ = ["Insight", "InsightVariable", "generate_insight_filters_hash", "resolve_insight_by_id_or_short_id"]
