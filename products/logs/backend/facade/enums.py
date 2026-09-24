"""Facade re-exports for logs enums referenced outside the product.

`ENUM_NAME_OVERRIDES` in `posthog/settings/web.py` resolves the OpenAPI component name from a
choices-class path, and that path must be a facade one so a refactor inside the product cannot
detach it silently.
"""

from products.logs.backend.models import LogsRetentionRule

# Record kind a logs rule applies to. `LogsMetricRule.RecordSource` declares the same
# (value, label) pairs, so drf-spectacular cannot tell the two apart by hash and both fields
# share this component name.
RecordSource = LogsRetentionRule.RecordSource

__all__ = ["RecordSource"]
