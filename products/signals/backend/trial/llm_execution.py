from uuid import uuid4

from posthog.llm.gateway_client import AIGatewayConfig, GatewayNotConfiguredError
from posthog.models import Team

from products.signals.backend.trial.billing import paid_trial_continuation_authorized
from products.signals.backend.trial.models import SignalTrialOperation
from products.signals.backend.trial.policy import OperationAdmission, TrialPolicy
from products.signals.backend.trial.reports import active_report_pass, report_trial_context, task_trial_context


class TrialLLMExecution:
    def __init__(self, policy: TrialPolicy, operation: SignalTrialOperation, *, owns_operation: bool) -> None:
        self.policy = policy
        self.operation = operation
        self.owns_operation = owns_operation

    @classmethod
    def prepare(cls, *, team_id: int | None, gateway: AIGatewayConfig | None) -> "TrialLLMExecution | None":
        if team_id is None:
            return None
        team = Team.objects.select_related("organization").get(id=team_id)
        policy = TrialPolicy(team)
        parent = None
        context = report_trial_context.get()
        task_context = task_trial_context.get()
        if task_context and task_context[0] == team_id:
            parent = (
                SignalTrialOperation.objects.for_team(policy.team_id, canonical=True)
                .filter(task_run_id=task_context[1])
                .first()
            )
            if parent is None:
                return None
        elif context and context[0] == team_id:
            parent = active_report_pass(team, context[1])
            if parent is None:
                return None
        grant = policy.grant()
        if parent is None and grant is None:
            return None
        paid_authorized = False
        if parent is None and (grant is None or grant.exhausted_at is not None):
            paid_authorized = paid_trial_continuation_authorized(team)
        operation = parent or policy.admit(
            OperationAdmission(operation_key=f"llm:{uuid4()}", stage=SignalTrialOperation.Stage.SHORT),
            paid_authorized=paid_authorized,
        )
        if operation.grant_id is None:
            if parent is None:
                policy.finish(operation.id)
            return None
        if gateway is None:
            if parent is None:
                policy.finish(operation.id)
            raise GatewayNotConfiguredError("Trial work requires accounted AI gateway execution")
        policy.start(operation.id, mark_started=operation.stage != SignalTrialOperation.Stage.REPORT_PASS)
        return cls(policy, operation, owns_operation=parent is None)

    def finish(self) -> None:
        if self.owns_operation:
            self.policy.finish(self.operation.id)
