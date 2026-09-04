from typing import Literal

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.instance_setting import get_instance_setting
from posthog.utils import get_instance_region

from products.growth.backend.models import OrganizationEnrichment
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_wizard_stamp_rescore

WizardStampRescoreSkipReason = Literal["disabled", "no_enrichment_record"]


@frozen
class WizardStampRescoreOutcome:
    queued: bool
    reason: WizardStampRescoreSkipReason | None = None


def _rescore_enabled() -> bool:
    try:
        return bool(get_instance_setting("GROWTH_SIGNUP_ENRICHMENT_ENABLED"))
    except Exception as e:
        capture_exception(e)
        return False


def request_wizard_stamp_rescore(organization_id: str) -> WizardStampRescoreOutcome:
    if not _rescore_enabled() or get_instance_region() not in ("US", "EU"):
        return WizardStampRescoreOutcome(queued=False, reason="disabled")

    if not OrganizationEnrichment.objects.filter(organization_id=organization_id).exists():
        return WizardStampRescoreOutcome(queued=False, reason="no_enrichment_record")

    dispatch_wizard_stamp_rescore(organization_id)
    return WizardStampRescoreOutcome(queued=True)
