from posthog.llm.gateway_client import AIGatewayConfig, GatewayNotConfiguredError
from posthog.models import Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.trial.billing import paid_trial_continuation_authorized
from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import context_funding, research_pass_started, task_trial_context
from products.tasks.backend.facade.api import get_task_run


class TrialLLMExecution:
    def __init__(self, funding: TrialFunding) -> None:
        self.funding = funding

    @classmethod
    def prepare(
        cls, *, team_id: int | None, gateway: AIGatewayConfig | None, signal_id: str | None = None
    ) -> "TrialLLMExecution | None":
        if team_id is None:
            return None
        team = Team.objects.select_related("organization").get(id=team_id)
        policy = TrialPolicy(team)
        parent = context_funding(team)
        spend = (
            SignalSpend.objects.for_team(team_id).filter(signal_id=signal_id, kind=SignalSpend.Kind.AD_HOC).first()
            if signal_id
            else None
        )
        if spend is not None:
            if spend.trial_grant_id is None:
                return None
            if parent is None or parent.grant_id != spend.trial_grant_id:
                parent = TrialFunding(funding="trial", grant_id=spend.trial_grant_id)
        grant = policy.active_grant()
        if parent is None and grant is None:
            return None
        if parent is not None and parent.grant_id is None:
            return None
        research_context = True
        task_context = task_trial_context.get()
        if task_context and task_context[0] == team_id:
            run = get_task_run(task_context[1], team_id=team_id)
            if run is None or run.is_terminal:
                raise TrialRefused("operation_finished")
            research_context = run.state.get("self_driving_funding", {}).get("stage") == "research"
        paid_authorized = False
        if parent is None and grant is not None and grant.exhausted_at:
            paid_authorized = paid_trial_continuation_authorized(team)
        funding = policy.admit(
            paid_authorized=paid_authorized,
            parent=parent,
            finishing_research=research_context and parent is not None and research_pass_started(team.id, parent),
        )
        if funding.grant_id is None:
            return None
        if gateway is None:
            raise GatewayNotConfiguredError("Trial work requires accounted AI gateway execution")
        return cls(funding)
