"""
Contract types for tracing.

Stable, framework-free frozen dataclasses that define what this
product exposes to the rest of the codebase.

Characteristics:
- No Django imports
- Immutable (frozen=True)
- Used by facade as inputs/outputs

Do NOT depend on Django models, DRF serializers, or request objects.
"""

from posthog.dataclasses import frozen

from products.tracing.backend.facade import enums


@frozen
class ServiceHealthParams:
    date_from: str = "-1h"
    date_to: str | None = None
    compare: enums.ServiceHealthCompare = enums.ServiceHealthCompare.PREVIOUS_PERIOD
    compare_date_from: str | None = None
    compare_date_to: str | None = None
    environment: str | None = None
    service_names: tuple[str, ...] = ()
    span_scope: enums.ServiceHealthSpanScope = enums.ServiceHealthSpanScope.ENTRY
    order_by: enums.ServiceHealthOrderBy = enums.ServiceHealthOrderBy.STATUS
    limit: int = 25
