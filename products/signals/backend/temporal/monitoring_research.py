from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.report_monitoring_research import MonitoringResearch
from products.signals.backend.temporal.agentic.report import RunAgenticReportInput, run_agentic_report_activity
from products.signals.backend.temporal.agentic.select_repository import (
    SelectRepositoryInput,
    github_optional_pilot_activity,
    select_repository_activity,
)
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeInput, report_safety_judge_activity
from products.signals.backend.temporal.types import SignalData


@activity.defn
@scoped_temporal()
@close_db_connections
async def research_monitoring_attempt_activity(request: MonitoringResearch) -> None:
    from products.signals.backend.temporal.summary import (  # noqa: PLC0415 -- breaks the report workflow import cycle
        CheckReportQuotaGateInput,
        check_report_quota_gate_activity,
    )

    if await check_report_quota_gate_activity(
        CheckReportQuotaGateInput(
            team_id=request.team_id, report_id=str(request.report_id), stage="monitoring_research"
        )
    ):
        return
    successor = await database_sync_to_async(request.prepare)()
    if successor is None:
        return
    context = await database_sync_to_async(request.context)()
    signals = [
        SignalData(
            signal_id=str(request.attempt_id),
            source_product="signals",
            source_type="monitoring",
            source_id=str(request.report_id),
            content=context,
            weight=1,
            timestamp=successor.created_at,
        )
    ]
    safety = await report_safety_judge_activity(
        SafetyJudgeInput(team_id=request.team_id, report_id=str(successor.id), signals=signals)
    )
    if not safety.safe:
        await database_sync_to_async(request.fail)(f"Failed safety review: {safety.explanation}")
        return
    github_optional = await github_optional_pilot_activity(request.team_id)
    selection = await select_repository_activity(
        SelectRepositoryInput(
            team_id=request.team_id,
            report_id=str(successor.id),
            signals=signals,
            github_optional=github_optional,
        )
    )
    if selection.repository is None and not github_optional:
        raise ValueError("Follow-up research requires repository selection")
    if await check_report_quota_gate_activity(
        CheckReportQuotaGateInput(team_id=request.team_id, report_id=str(successor.id), stage="pre_research")
    ):
        return
    if await database_sync_to_async(request.prepare)() is None:
        return
    result = await run_agentic_report_activity(
        RunAgenticReportInput(
            team_id=request.team_id,
            report_id=str(successor.id),
            signals=signals,
            repo_selection=selection,
            github_optional=github_optional,
        )
    )
    await database_sync_to_async(request.finish)(result)


@activity.defn
@scoped_temporal()
@close_db_connections
async def fail_monitoring_research_activity(request: MonitoringResearch, error: str) -> None:
    await database_sync_to_async(request.fail)(error)


@workflow.defn(name="signals-monitoring-research")
class MonitoringResearchWorkflow:
    @workflow.run
    async def run(self, request: MonitoringResearch) -> None:
        try:
            await workflow.execute_activity(
                research_monitoring_attempt_activity,
                request,
                start_to_close_timeout=timedelta(hours=4),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=10)),
            )
        except ActivityError as error:
            await workflow.execute_activity(
                fail_monitoring_research_activity,
                args=[request, str(error.cause or error)],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
