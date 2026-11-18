"""Facade re-export for span retention rules, for the Logs retention entitlement resets in core."""

from products.tracing.backend.models import TracesRetentionRule

__all__ = ["TracesRetentionRule"]
