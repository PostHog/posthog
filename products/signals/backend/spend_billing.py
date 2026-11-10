from collections.abc import Collection
from datetime import UTC, date, datetime
from uuid import UUID

from django.utils import timezone

import structlog
import posthoganalytics

from posthog.models import Team

from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.free_trial import SELF_DRIVING_FREE_TRIAL_FLAG
from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.usage import spend_credits_by_team

logger = structlog.get_logger(__name__)


def system_source_exempt(source_product: str | None) -> bool:
    return source_product in {SignalSourceProduct.HEALTH_CHECKS, SignalSourceProduct.ENGINEERING_ANALYTICS}


def scout_skill_spend_exempt(team_id: int, skill_name: str, skill_version: int | None) -> bool:
    from products.signals.backend.billing import (  # noqa: PLC0415 — billing uses this module for aggregation
        BILLING_EXEMPT_SCOUT_RUN_SKILLS,
        _scout_skill_is_canonical,
    )

    return skill_name in BILLING_EXEMPT_SCOUT_RUN_SKILLS and _scout_skill_is_canonical(
        team_id, skill_name, version=skill_version
    )


def scout_spend_exempt(scout: SignalScoutRun) -> bool:
    return scout.trial_state is not None or scout_skill_spend_exempt(
        scout.team_id, scout.skill_name, scout.skill_version
    )


def trial_spend_exempt(team_id: int) -> bool:
    from products.signals.backend.trial.models import (
        SignalTrialGrant,  # noqa: PLC0415 -- avoids model registration cycles
    )

    team = Team.objects.only("parent_team_id").get(id=team_id)
    if SignalTrialGrant.objects.for_team(team.parent_team_id or team_id, canonical=True).exists():
        return False
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


def uses_spend_billing(team_id: int, *, started_at: datetime | None = None) -> bool:
    cutoff = Team.objects.values_list("organization__usage__signals_spend_credits__billing_start_date", flat=True).get(
        id=team_id
    )
    return bool(cutoff and (started_at or timezone.now()).astimezone(UTC).date() >= date.fromisoformat(cutoff))


def get_signals_spend_billing_credits_by_team(
    begin: datetime,
    end: datetime,
    organization_id: str | UUID | None = None,
    organization_ids: Collection[str | UUID] | None = None,
) -> list[tuple[int, int]]:  # nosemgrep: tuple-return-prefer-dataclass -- usage-counter contract
    return list(
        spend_credits_by_team(
            begin, end, organization_id=organization_id, organization_ids=organization_ids, include_running=False
        ).items()
    )


def get_signals_spend_quota_credits_by_team(
    begin: datetime,
    end: datetime,
    organization_id: str | UUID | None = None,
) -> list[tuple[int, int]]:  # nosemgrep: tuple-return-prefer-dataclass -- usage-counter contract
    return list(spend_credits_by_team(begin, end, organization_id=organization_id, include_running=True).items())


def apply_report_billing(spend: SignalSpend, report: SignalReport) -> None:
    if report.billing_exempt_reason:
        spend.billing_exempt = True
