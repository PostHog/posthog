from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

from django.conf import settings

import structlog
from anthropic import AsyncAnthropic

from posthog.llm.gateway_client import (
    AIGatewayConfig,
    GatewayNotConfiguredError,
    build_async_anthropic_client,
    resolve_ai_gateway_config,
)
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.trial_billing import paid_trial_continuation_authorized
from products.signals.backend.trial_models import SignalTrialOperation
from products.signals.backend.trial_policy import OperationAdmission, TrialPolicy
from products.signals.backend.trial_reports import active_report_pass, report_trial_context, task_trial_context
from products.signals.backend.trial_tasks import reconcile_trial_operation
from products.tasks.backend.facade.gateway import mint_trial_gateway_token, revoke_private_gateway_token

logger = structlog.get_logger(__name__)


class TrialLLMExecution:
    def __init__(
        self, policy: TrialPolicy, operation: SignalTrialOperation, gateway: AIGatewayConfig, *, owns_operation: bool
    ) -> None:
        self.policy = policy
        self.operation = operation
        self.gateway = gateway
        self.owns_operation = owns_operation

    @classmethod
    def prepare(cls, *, team_id: int | None, model: str) -> "TrialLLMExecution | None":
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
        decision = policy.flag_decision()
        if decision.enabled is not True and parent is None:
            return None
        grant = policy.grant()
        if parent is None and grant is None and not settings.SELF_DRIVING_TRIAL_V2_BILLING_READY:
            return None
        paid_authorized = False
        if parent is None and (grant is None or grant.exhausted_at is not None):
            paid_authorized = paid_trial_continuation_authorized(team)
        operation = parent or policy.admit(
            OperationAdmission(
                operation_key=f"llm:{uuid4()}",
                stage=SignalTrialOperation.Stage.SHORT,
                estimated_microusd=settings.SELF_DRIVING_TRIAL_RESERVATIONS_MICROUSD["short"],
                model=model,
                runtime="anthropic",
            ),
            paid_authorized=paid_authorized,
            decision=decision,
        )
        if operation.grant_id is None:
            return None
        request_cap = settings.SELF_DRIVING_TRIAL_RESERVATIONS_MICROUSD["short"]
        if parent is not None:
            policy.reserve_finalization(operation.id, request_cap)
        try:
            config = resolve_ai_gateway_config()
            if config is None:
                raise GatewayNotConfiguredError("Free trial work requires the accounted AI gateway")
            token = mint_trial_gateway_token(
                team_id=team_id,
                funding={
                    "grant_id": str(operation.grant_id),
                    "operation_id": str(operation.id),
                    "policy_version": operation.policy_version,
                },
                cap_usd=str(Decimal(request_cap) / 1_000_000),
                model=model,
                gateway_config=config,
            )
        except Exception:
            if parent is None:
                policy.finish(operation.id)
            reconcile_trial_operation.delay(policy.team_id, str(operation.id))
            raise
        return cls(policy, operation, AIGatewayConfig(url=config.url, api_key=token), owns_operation=parent is None)

    def before_request(self) -> None:
        self.policy.start(
            self.operation.id, mark_started=self.operation.stage != SignalTrialOperation.Stage.REPORT_PASS
        )

    def record_request(self, request_id: str | None) -> None:
        # The gateway persists request identity before dispatch, including requests whose callback is lost.
        reconcile_trial_operation.delay(self.policy.team_id, str(self.operation.id))

    def finish(self) -> None:
        if self.owns_operation:
            self.policy.finish(self.operation.id)
        reconcile_trial_operation.delay(self.policy.team_id, str(self.operation.id))


@asynccontextmanager
async def trial_llm_execution(*, team_id: int | None, model: str) -> AsyncIterator[TrialLLMExecution | None]:
    execution = await database_sync_to_async(TrialLLMExecution.prepare, thread_sensitive=False)(
        team_id=team_id, model=model
    )
    try:
        yield execution
    finally:
        if execution is not None:
            try:
                await database_sync_to_async(revoke_private_gateway_token, thread_sensitive=False)(
                    execution.gateway.api_key, gateway_config=resolve_ai_gateway_config()
                )
            except Exception:
                # The bounded token expires; recovery retains the hold until accounting is complete.
                logger.warning("signals_trial_token_revocation_pending", operation_id=str(execution.operation.id))
            finally:
                await database_sync_to_async(execution.finish, thread_sensitive=False)()


@asynccontextmanager
async def accounted_anthropic_client(
    client: AsyncAnthropic, *, team_id: int, model: str
) -> AsyncIterator[AsyncAnthropic]:
    async with trial_llm_execution(team_id=team_id, model=model) as trial:
        if trial is None:
            yield client
            return
        await database_sync_to_async(trial.before_request)()
        async with build_async_anthropic_client(
            product="signals", ai_product="signals", team_id=team_id, gateway_config=trial.gateway
        ).with_options(max_retries=0) as accounted:
            try:
                yield accounted
            finally:
                await database_sync_to_async(trial.record_request)(None)
