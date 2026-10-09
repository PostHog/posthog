"""Compute quota exports for the tasks product.

The Cloud Agents functions give the Cloud Agents product its own quota answers: a stable denial
code, the reset time for ``Retry-After``, and the teams whose active runs a periodic sweep must stop.
"""

from products.tasks.backend.logic.services.compute_quota import (
    CloudAgentsQuotaDenial,
    cloud_agents_quota_denial,
    cloud_agents_quota_reset_at,
    list_teams_over_cloud_agents_quota_with_active_runs,
)


class ComputeBillingLimitExceeded(Exception):
    reason = "posthog_code_billing_limit_exceeded"


__all__ = [
    "CloudAgentsQuotaDenial",
    "ComputeBillingLimitExceeded",
    "cloud_agents_quota_denial",
    "cloud_agents_quota_reset_at",
    "list_teams_over_cloud_agents_quota_with_active_runs",
]
