"""Facade re-export for the retention-rule viewset.

The tracing product subclasses it for span retention rules, which share this implementation
with the record source pinned by the route.
"""

from products.logs.backend.presentation.views.retention_api import LogsRetentionRuleViewSet

__all__ = ["LogsRetentionRuleViewSet"]
