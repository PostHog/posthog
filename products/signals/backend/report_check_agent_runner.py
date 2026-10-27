from __future__ import annotations

import json
import asyncio
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import STEP_SCOUT, resolve_agent_runtime
from products.signals.backend.models import SignalReportAgentEvaluation, SignalReportCheck
from products.signals.backend.report_check_agent import (
    AGENT_CHECK_RESULT_WINDOW,
    _refuse_dispatch,
    resolve_check_skill_name,
)
from products.signals.backend.report_check_agent_context import AGENT_MONITORING_PROMPT, build_agent_context
from products.signals.backend.report_check_final_agents import (
    AgentMonitoringResult,
    _assert_user_access,
    _locked_evaluation,
    _queries_for_attempt,
    abandon_agent_evaluation,
    bind_agent_run,
    deliver_agent_result,
    stage_agent_result,
)
from products.signals.backend.report_checks import AgentCheckConfig, parse_check_config
from products.signals.backend.report_monitoring_results import InvalidMonitoringResult
from products.signals.backend.scout_harness.limits import DEFAULT_MAX_RUNTIME_S, WORKFLOW_HARD_CEILING_S
from products.signals.backend.temporal.agentic import get_or_create_signals_sandbox_env, resolve_acting_user_id_for_team
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession
from products.tasks.backend.facade.contracts import SessionFile


def agent_dispatch_refused(check: SignalReportCheck, *, evaluation_id: UUID | None = None) -> bool:
    team = check.report.team
    canonical_team_id = team.parent_team_id or team.id
    config = parse_check_config(check.kind, check.config)
    assert isinstance(config, AgentCheckConfig)
    skill_name = resolve_check_skill_name(config, canonical_team_id)
    return _refuse_dispatch(skill_name, canonical_team_id, monitoring_evaluation_id=evaluation_id) is not None


def _prepare(team_id: int, evaluation_id: UUID) -> SignalReportAgentEvaluation | None:
    with transaction.atomic():
        evaluation = _locked_evaluation(team_id, evaluation_id)
        if evaluation.state != evaluation.State.PENDING:
            return None
        if evaluation.created_at + AGENT_CHECK_RESULT_WINDOW <= timezone.now():
            return None
        if agent_dispatch_refused(evaluation.report_check, evaluation_id=evaluation.id):
            evaluation.state = evaluation.State.ABANDONED
            evaluation.save(update_fields=["state"])
            return None
        user_id = resolve_acting_user_id_for_team(team_id)
        if user_id is None:
            raise InvalidMonitoringResult("No user can investigate this report environment.")
        _assert_user_access(evaluation.report, user_id)
        evaluation.user_id = user_id
        return evaluation


async def _run_monitoring_agent(*, team_id: int, evaluation_id: UUID) -> None:
    evaluation = await database_sync_to_async(_prepare, thread_sensitive=False)(team_id, evaluation_id)
    if evaluation is None or evaluation.user_id is None:
        return
    context_file = await database_sync_to_async(build_agent_context, thread_sensitive=False)(evaluation)
    queries = await database_sync_to_async(_queries_for_attempt, thread_sensitive=False)(evaluation.report)
    sandbox_env = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
        team_id, "SIGNALS_MONITORING_CHECK", tasks_facade.SandboxNetworkAccessLevel.TRUSTED
    )
    team = await Team.objects.aget(id=team_id)
    runtime = await asyncio.to_thread(resolve_agent_runtime, team.parent_team_id or team.id, STEP_SCOUT)
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=evaluation.user_id,
        sandbox_environment_id=sandbox_env,
        posthog_mcp_scopes="signals_monitoring",
        github_read_access=True,
        model=runtime.model,
        runtime_adapter=runtime.runtime_adapter,
        reasoning_effort=runtime.reasoning_effort,
        service_tier=runtime.service_tier,
        runtime=runtime.runtime,
        initial_permission_mode="full-access" if runtime.runtime_adapter == "codex" else "bypassPermissions",
        sandbox_timeout_seconds=WORKFLOW_HARD_CEILING_S,
    )

    user_id = evaluation.user_id

    def bind(task_run_id: UUID) -> None:
        bind_agent_run(team_id=team_id, evaluation_id=evaluation_id, task_run_id=task_run_id, user_id=user_id)

    session, result = await MultiTurnSession.start(
        prompt=AGENT_MONITORING_PROMPT + "\nResult schema:\n" + json.dumps(AgentMonitoringResult.model_json_schema()),
        context=context,
        model=AgentMonitoringResult,
        step_name="monitoring_authored_check",
        origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
        signal_report_id=str(evaluation.report_id),
        ai_stage="monitoring_authored_check",
        internal=True,
        before_task_dispatch=bind,
        max_poll_seconds=DEFAULT_MAX_RUNTIME_S,
        analytics_query_context=queries or None,
        mcp_gateway_server_ids=[],
        files=[SessionFile(name="monitoring-check.json", content=context_file)],
    )
    end_status = "completed"
    end_error: str | None = None
    try:
        await database_sync_to_async(stage_agent_result, thread_sensitive=False)(
            team_id=team_id, evaluation_id=evaluation_id, task_run_id=session.task_run.id, result=result
        )
    except BaseException as error:
        end_status = "cancelled" if isinstance(error, (InvalidMonitoringResult, asyncio.CancelledError)) else "failed"
        end_error = str(error)
        raise
    finally:
        await asyncio.shield(session.end(status=end_status, error=end_error))
    await database_sync_to_async(deliver_agent_result, thread_sensitive=False)(
        team_id=team_id, evaluation_id=evaluation_id
    )


async def run_monitoring_agent(*, team_id: int, evaluation_id: UUID) -> None:
    try:
        await _run_monitoring_agent(team_id=team_id, evaluation_id=evaluation_id)
    except InvalidMonitoringResult:
        # Task creation can roll back its dispatch callback, so abandon after that transaction exits.
        await database_sync_to_async(abandon_agent_evaluation, thread_sensitive=False)(
            team_id=team_id, evaluation_id=evaluation_id
        )
