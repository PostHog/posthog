"""Test-support facade for subscriptions.

Suites outside this product read what they need to build subscription fixtures from here.
"""

from products.subscriptions.backend.temporal.ai_subscription.spec_generator import (
    AI_QUERY_PLAN_VERSION as AI_QUERY_PLAN_VERSION,
)

__all__ = ["AI_QUERY_PLAN_VERSION"]
