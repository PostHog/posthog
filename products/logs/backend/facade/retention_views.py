"""Facade re-export for the retention-rule viewset and serializer.

The tracing product subclasses both for span retention rules, which share this implementation
over their own model.
"""

from products.logs.backend.presentation.views.retention_api import LogsRetentionRuleSerializer, LogsRetentionRuleViewSet

__all__ = ["LogsRetentionRuleSerializer", "LogsRetentionRuleViewSet"]
