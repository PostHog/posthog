from uuid import UUID

from django.db import models

import structlog

from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.models import Organization, Team

from ee.billing.billing_manager import BILLING_SERVICE_URL, BillingManager, handle_billing_service_error, http_session
from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)


class TrialContinuation(models.TextChoices):
    PAID = "continue_paid", "Continue under existing paid authorization"
    PAYMENT = "add_payment_method", "Add a payment method"
    LIMIT = "increase_limit", "Increase the Self-driving spending limit"
    ENABLE = "enable_self_driving", "Enable paid Self-driving"
    UNAVAILABLE = "unavailable", "Billing status unavailable"


@frozen
class TrialBillingStatus:
    ready: bool
    migrated: bool
    continuation: TrialContinuation

    @property
    def paid_authorized(self) -> bool:
        return self.continuation == TrialContinuation.PAID


class TrialBilling:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    def status(self, *, grant_id: UUID | None = None) -> TrialBillingStatus:
        manager = BillingManager(get_cached_instance_license())
        headers = manager.get_auth_headers(self.organization, service_action="self_driving_trial")
        url = f"{BILLING_SERVICE_URL}/api/signals/trial/"
        if grant_id is None:
            response = http_session.get(url, headers=headers, timeout=5)
        else:
            response = http_session.post(url, headers=headers, json={"grant_id": str(grant_id)}, timeout=5)
        handle_billing_service_error(response, valid_codes=(200,))
        data = response.json()
        if type(data.get("ready")) is not bool or type(data.get("migrated")) is not bool:
            raise ValueError("Billing did not acknowledge the one-time trial policy")
        return TrialBillingStatus(
            ready=data["ready"], migrated=data["migrated"], continuation=TrialContinuation(data["continuation"])
        )


def paid_trial_continuation_authorized(team: Team) -> bool:
    try:
        return TrialBilling(team.organization).status().paid_authorized and not is_team_limited(
            team.api_token, QuotaResource.SIGNALS_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
    except Exception:
        logger.warning("signals_trial_paid_authorization_unavailable", team_id=team.id, exc_info=True)
        return False
