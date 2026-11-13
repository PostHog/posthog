from typing import TYPE_CHECKING

from products.signals.backend.agent_runtime import AgentRuntime
from products.signals.backend.trial.billing import TrialContinuation, trial_billing_status
from products.signals.backend.trial.policy import TrialPolicy
from products.signals.backend.usage import trial_usage

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from posthog.models import Team

    from products.signals.backend.models import SignalScoutConfig


def trial_counted_scouts(team_id: int) -> "QuerySet[SignalScoutConfig]":
    from products.signals.backend.models import SignalScoutConfig  # noqa: PLC0415 -- model registration cycle
    from products.signals.backend.scout_harness.operational import (  # noqa: PLC0415 -- keeps the canonical fleet off the model import path
        unedited_operational_skill_names,
    )

    return (
        SignalScoutConfig.objects.for_team(team_id, canonical=True)
        .filter(enabled=True)
        .exclude(skill_name__in=unedited_operational_skill_names(team_id))
    )


def trial_scout_runtime(team: "Team") -> AgentRuntime | None:
    grant = TrialPolicy(team).active_grant()
    if grant is None or trial_usage(grant).exhaustion_reason(grant):
        return None
    decision = TrialPolicy(team).flag_decision()
    if not decision.confirmed or decision.enabled is not True:
        return None
    billing = trial_billing_status(team)
    if not billing.ready or billing.continuation != TrialContinuation.PAYMENT:
        return None
    # Billing exposes a subscription, not card presence. A provider customer can already have a
    # saved card before activating a subscription, so keep its normal model too.
    if team.organization.customer_id:
        return None
    return AgentRuntime(runtime_adapter="codex", model="gpt-5.6-luna", service_tier="flex")
