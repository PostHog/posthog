"""Temporal wiring of the web_analytics facade.

Core's worker bootstrap and schedule registration import the product's
workflows, activities, and schedule input types. Re-export exactly those so
the worker/beat wiring crosses the boundary through the facade.
"""

from products.web_analytics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.web_analytics.backend.temporal.weekly_digest.types import SendTestDigestInput, WAWeeklyDigestInput

__all__ = ["ACTIVITIES", "WORKFLOWS", "SendTestDigestInput", "WAWeeklyDigestInput"]
