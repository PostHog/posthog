from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.db import transaction

import structlog

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.trial.billing import TrialBilling, TrialContinuation
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy, lock_organization_trial

if TYPE_CHECKING:
    from posthog.models import Team

    from products.signals.backend.models import SignalScoutConfig

logger = structlog.get_logger(__name__)


@contextmanager
def scout_capacity(config: "SignalScoutConfig") -> Iterator[None]:
    from products.signals.backend.models import SignalScoutConfig  # noqa: PLC0415 -- model registration cycle

    if not config.enabled:
        yield
        return
    team = config.team
    policy = TrialPolicy(team)
    if not policy.enabled():
        yield
        return
    team_id = team.parent_team_id or team.id
    with transaction.atomic():
        previous = (
            SignalScoutConfig.objects.for_team(team_id, canonical=True).select_for_update().filter(id=config.id).first()
        )
        if previous is not None and previous.enabled:
            yield
            return
        lock_organization_trial(team.organization_id)
        grant = SignalTrialGrant.objects.for_team(team_id, canonical=True).filter(exhausted_at__isnull=True).first()
        if grant is not None:
            count = (
                SignalScoutConfig.objects.for_team(team_id, canonical=True)
                .filter(enabled=True)
                .exclude(id=config.id)
                .count()
            )
            if count >= grant.scout_limit:
                if not config._state.adding:
                    from rest_framework.exceptions import (
                        ValidationError,  # noqa: PLC0415 -- only API writes need the error renderer
                    )

                    raise ValidationError(
                        {"enabled": "The free trial allows three enabled scouts. Pause one before enabling another."}
                    )
                config.enabled = False
                config.status = SignalScoutConfig.Status.PAUSED_BY_SYSTEM
                config.pause_reason = SignalScoutConfig.PauseReason.TRIAL_SCOUT_LIMIT
        yield


def trial_scout_limit(team_id: int) -> int | None:
    from posthog.models import Team  # noqa: PLC0415 -- avoid model registration cycle

    grant = TrialPolicy(Team.objects.get(id=team_id)).active_grant()
    return grant.scout_limit if grant is not None and grant.exhausted_at is None else None


def trial_scout_runtime(team: "Team") -> AgentRuntime | None:
    if trial_scout_limit(team.parent_team_id or team.id) is None:
        return None
    decision = TrialPolicy(team).flag_decision()
    if not decision.confirmed or decision.enabled is not True:
        return None
    try:
        billing = TrialBilling(team.organization).status()
    except Exception:
        logger.warning("signals_trial_scout_billing_unavailable", team_id=team.id, exc_info=True)
        return None
    if not billing.ready or billing.continuation != TrialContinuation.PAYMENT:
        return None
    # Billing exposes a subscription, not card presence. A provider customer can already have a
    # saved card before activating a subscription, so keep its normal model too.
    if team.organization.customer_id:
        return None
    return AgentRuntime(runtime_adapter="codex", model="gpt-6-luna")
