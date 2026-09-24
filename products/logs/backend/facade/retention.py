"""Facade re-exports for retention rules.

The presentation layer must reach product internals through the facade, and this keeps the
LLM client out of ``facade/api.py`` so config-only consumers don't drag it onto the
``django.setup()`` path.

The viewset lives in ``facade/retention_views.py`` instead: the viewset module imports this
one for the name suggestion, so re-exporting it here would be a cycle.
"""

from products.logs.backend.models import LogsRetentionRule
from products.logs.backend.retention_name_suggestion import suggest_retention_rule_name

# Record sources a retention rule can be pinned to, as plain strings so consumers do not need
# the model class.
RETENTION_RULE_SOURCE_LOGS: str = LogsRetentionRule.RecordSource.LOGS
RETENTION_RULE_SOURCE_SPANS: str = LogsRetentionRule.RecordSource.SPANS

__all__ = [
    "RETENTION_RULE_SOURCE_LOGS",
    "RETENTION_RULE_SOURCE_SPANS",
    "suggest_retention_rule_name",
]
