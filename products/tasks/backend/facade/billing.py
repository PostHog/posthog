"""
Facade re-exports for PostHog Code billing.

The usage report (``posthog/tasks/usage_report.py``) excludes seat-covered generations from
the billed ``posthog_code_credits`` counter using the seat roster fetched from the billing
service; it imports the lookup from here rather than reaching the internal ``billing`` module.
"""

from products.tasks.backend.billing import POSTHOG_CODE_PRODUCT_KEY, get_seat_covered_distinct_ids

__all__ = ["POSTHOG_CODE_PRODUCT_KEY", "get_seat_covered_distinct_ids"]
