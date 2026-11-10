from typing import Any

import structlog

from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Team

from ee.billing.billing_manager import BillingManager

logger = structlog.get_logger(__name__)


def get_organization_billing(team_id: int) -> dict[str, Any] | None:
    """The billing service's view of the team's organization, read with the instance license.

    Server-side on purpose: the user who started the run may not have billing access, and their token never
    needs it.
    """
    organization = Team.objects.select_related("organization").get(id=team_id).organization
    license = get_cached_instance_license()
    if license is None or not license.is_v2_license:
        return None

    try:
        return BillingManager(license).get_billing(organization)
    except Exception:
        logger.warning("wizard_spend_audit_billing_unavailable", team_id=team_id, exc_info=True)
        return None
