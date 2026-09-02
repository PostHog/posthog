"""Facade re-export for retention-rule name suggestion.

The presentation layer must reach product internals through the facade, and this keeps the
LLM client out of ``facade/api.py`` so config-only consumers don't drag it onto the
``django.setup()`` path.
"""

from products.logs.backend.retention_name_suggestion import suggest_retention_rule_name

__all__ = ["suggest_retention_rule_name"]
