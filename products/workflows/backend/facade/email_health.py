"""Email health: sending rates, the AWS SES tenant verdict, the per-ISP breakdown, the sending
allowance, the shared infrastructure's health, the project-wide suspension, the per-workflow pause
and the email steps whose sender cannot send."""

from products.workflows.backend.services.email_health import (
    email_domain_sharers,
    email_infrastructure_health_enabled,
    fetch_aws_tenant_reputation,
    fetch_email_infrastructure_health,
    fetch_email_totals_by_source,
    fetch_isp_metrics,
    fold_email_totals,
    team_email_sending_allowance,
    verified_email_domains,
)
from products.workflows.backend.services.email_sending_controls import get_email_sending_state
from products.workflows.backend.services.workflow_email_health import pause_requires_staff, resume_email_sending
from products.workflows.backend.services.workflow_email_senders import unusable_email_steps

__all__ = [
    "email_domain_sharers",
    "email_infrastructure_health_enabled",
    "fetch_aws_tenant_reputation",
    "fetch_email_infrastructure_health",
    "fetch_email_totals_by_source",
    "fetch_isp_metrics",
    "fold_email_totals",
    "get_email_sending_state",
    "pause_requires_staff",
    "resume_email_sending",
    "team_email_sending_allowance",
    "unusable_email_steps",
    "verified_email_domains",
]
