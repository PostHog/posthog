from typing import Literal

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.instance_setting import get_instance_setting
from posthog.temporal.health_checks.rollups.store import delete_rollup_rows_for_teams
from posthog.utils import get_instance_region

from products.growth.backend.models import OrganizationEnrichment, SdkVersionsDaily
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_wizard_stamp_rescore

WizardStampRescoreSkipReason = Literal["disabled", "no_enrichment_record", "dispatch_backlog_full", "dispatch_failed"]


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

    failure = dispatch_wizard_stamp_rescore(organization_id)
    if failure is not None:
        return WizardStampRescoreOutcome(queued=False, reason=failure)
    return WizardStampRescoreOutcome(queued=True)


def delete_sdk_version_rollups_for_teams(team_ids: list[int]) -> None:
    """Remove the SDK version rollup rows of the given environments. Called from team deletion."""
    delete_rollup_rows_for_teams(SdkVersionsDaily, team_ids)
