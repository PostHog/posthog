"""Facade re-export for the tracing team-extension model.

Core's ``posthog/api/team.py`` registers/reads this extension by class identity
through ``get_or_create_team_extension``. Re-exporting the model class keeps
that registry coupling at the facade boundary without exposing the internal
models module. Mirrors the customer_analytics precedent.
"""

from products.tracing.backend.models import (
    DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEYS,
    DEFAULT_TRACING_SESSION_ID_ATTRIBUTE_KEYS,
    TeamTracingConfig,
)

__all__ = [
    "DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEYS",
    "DEFAULT_TRACING_SESSION_ID_ATTRIBUTE_KEYS",
    "TeamTracingConfig",
]
