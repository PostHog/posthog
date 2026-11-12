from posthog.llm.gateway_client import AIGatewayConfig, GatewayNotConfiguredError
from posthog.models import Team

from products.signals.backend.quota import prepare_self_driving_admission
from products.signals.backend.trial.funding import TrialFunding, signal_funding
from products.signals.backend.trial.policy import TrialRefused
from products.signals.backend.trial.reports import context_funding, task_trial_context
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
        parent = context_funding(team)
        if parent is not None and parent.funding == "operator":
            return cls(parent)
        parent = signal_funding(team_id, signal_id) or parent
        funding = prepare_self_driving_admission(team, parent=parent).bind()
        if funding.grant_id is None:
            return None
        task_context = task_trial_context.get()
        if task_context and task_context[0] == team_id:
            run = get_task_run(task_context[1], team_id=team_id)
            if run is None or run.is_terminal:
                raise TrialRefused("operation_finished")
        if gateway is None:
            raise GatewayNotConfiguredError("Trial work requires accounted AI gateway execution")
        return cls(funding)
