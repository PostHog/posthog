import posthoganalytics

from posthog.models import Team

from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.free_trial import SELF_DRIVING_FREE_TRIAL_FLAG
from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend


def system_source_exempt(source_product: str | None) -> bool:
    return source_product in {SignalSourceProduct.HEALTH_CHECKS, SignalSourceProduct.ENGINEERING_ANALYTICS}


def scout_spend_exempt(scout: SignalScoutRun) -> bool:
    from products.signals.backend.billing import (  # noqa: PLC0415 — billing uses this module for aggregation
        BILLING_EXEMPT_SCOUT_SKILLS,
        _scout_skill_is_canonical,
    )

    return scout.trial_state is not None or (
        scout.skill_name in BILLING_EXEMPT_SCOUT_SKILLS
        and _scout_skill_is_canonical(scout.team_id, scout.skill_name, version=scout.skill_version)
    )


def trial_spend_exempt(team_id: int) -> bool:
    org_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
    return (
        posthoganalytics.feature_enabled(
            SELF_DRIVING_FREE_TRIAL_FLAG,
            org_id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        is True
    )


def apply_report_billing(spend: SignalSpend, report: SignalReport) -> None:
    if report.billing_exempt_reason:
        spend.billing_exempt = True
