from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_background_capture
from posthog.utils import get_instance_region

from products.signals.backend.trial.limits import STANDARD_TRIAL_LIMITS, TrialLimits

if TYPE_CHECKING:
    from products.signals.backend.trial.models import SignalTrialGrant

TRIAL_REPORT_LIMIT_EXPERIMENT = "self-driving-trial-report-limit"


def resolve_trial_limits(organization_id: UUID, limits: TrialLimits) -> tuple[TrialLimits, str | None]:
    if limits != STANDARD_TRIAL_LIMITS:
        return limits, None

    org = str(organization_id)
    try:
        variant = posthoganalytics.get_feature_flag(
            TRIAL_REPORT_LIMIT_EXPERIMENT,
            org,
            groups={"organization": org},
            group_properties={"organization": {"id": org}},
            send_feature_flag_events=False,
        )
    except Exception as error:
        capture_exception(error)
        return limits, None

    if variant == "test":
        return replace(limits, report_limit=10), "test"
    return limits, "control" if variant == "control" else None


def capture_trial_exposure(grant: "SignalTrialGrant", variant: str) -> None:
    capture = ph_background_capture(event_region=get_instance_region())
    capture(
        distinct_id=str(grant.organization_id),
        event="$experiment_exposure",
        groups={"organization": str(grant.organization_id)},
        properties={
            "$feature_flag": TRIAL_REPORT_LIMIT_EXPERIMENT,
            "$feature_flag_response": variant,
            f"$feature/{TRIAL_REPORT_LIMIT_EXPERIMENT}": variant,
            "grant_id": str(grant.id),
        },
    )
