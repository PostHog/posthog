import json
from dataclasses import dataclass
from typing import TypedDict

from django.db import transaction

import structlog
import temporalio
from pydantic import ValidationError

from posthog.models import Team, User
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.models import SignalAutonomyConfig, SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    ReportResearchOutput,
    SignalFinding,
    run_multi_turn_research,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    get_org_member_github_login_to_user_map,
    resolve_suggested_reviewers,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.models import SandboxEnvironment, Task
from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

logger = structlog.get_logger(__name__)


class ReviewerContent(TypedDict):
    github_login: str
    github_name: str | None
    relevant_commits: list[dict]


class TaskRunArtefactContent(TypedDict):
    task_id: str
    task_run_id: str
    repository: str
    title: str


@dataclass
class RunAgenticReportInput:
    team_id: int
    report_id: str
    signals: list[SignalData]
    repo_selection: RepoSelectionResult


@dataclass
class RunAgenticReportOutput:
    title: str
    summary: str
    choice: ActionabilityChoice
    priority: Priority | None
    explanation: str
    already_addressed: bool
    repository: str


async def _load_previous_research(report_id: str) -> ReportResearchOutput | None:
    """Reconstruct the previous report state."""
    report = await SignalReport.objects.filter(id=report_id).only("title", "summary").afirst()
    if report is None or not report.title or not report.summary:
        logger.info(
            "load previous research: no report or missing title/summary, treating as first run",
            report_id=report_id,
            has_report=report is not None,
        )
        return None

    artefacts_qs = SignalReportArtefact.objects.filter(
        report_id=report_id,
        # Only types we care about for the agentic report generation
        type__in=[
            SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
            SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
        ],
    ).order_by("created_at")

    findings: list[SignalFinding] = []
    actionability: ActionabilityAssessment | None = None
    priority: PriorityAssessment | None = None

    async for artefact in artefacts_qs:
        match artefact.type:
            case SignalReportArtefact.ArtefactType.SIGNAL_FINDING:
                findings.append(SignalFinding.model_validate_json(artefact.content))
            case SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT:
                try:
                    actionability = ActionabilityAssessment.model_validate_json(artefact.content)
                except ValidationError:
                    logger.warning(
                        "Ignoring actionability artefact with incompatible schema (likely written by the legacy path)",
                        report_id=report_id,
                        artefact_id=artefact.id,
                    )
            case SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT:
                priority = PriorityAssessment.model_validate_json(artefact.content)

    if not findings or actionability is None:
        logger.info(
            "load previous research: missing artefacts, treating as first run",
            report_id=report_id,
            finding_count=len(findings),
            has_actionability=actionability is not None,
        )
        return None

    return ReportResearchOutput(
        title=report.title,
        summary=report.summary,
        findings=findings,
        actionability=actionability,
        priority=priority,
    )


_AGENTIC_ARTEFACT_TYPES = [
    SignalReportArtefact.ArtefactType.REPO_SELECTION,
    SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
    SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
    SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
]


def _build_reviewers_content(
    team_id: int,
    repository: str,
    findings: list[SignalFinding],
) -> list[ReviewerContent]:
    commit_hashes_with_reasons: dict[str, str] = {}
    for finding in findings:
        for sha, reason in finding.relevant_commit_hashes.items():
            if sha and sha not in commit_hashes_with_reasons:
                commit_hashes_with_reasons[sha] = str(reason) if reason else ""

    if not commit_hashes_with_reasons or not repository:
        return []

    resolved = resolve_suggested_reviewers(team_id, repository, commit_hashes_with_reasons)
    if not resolved:
        return []

    reviewers_content: list[ReviewerContent] = []
    for reviewer in resolved:
        reviewers_content.append(
            ReviewerContent(
                github_login=reviewer.login.lower(),
                github_name=reviewer.name,
                relevant_commits=[dict(commit.model_dump()) for commit in reviewer.commits],
            )
        )
    return reviewers_content


def _priority_rank(priority: Priority) -> int:
    return {
        Priority.P0: 0,
        Priority.P1: 1,
        Priority.P2: 2,
        Priority.P3: 3,
        Priority.P4: 4,
    }[priority]


def _build_autostart_task_description(result: ReportResearchOutput, repository: str) -> str:
    priority_line = (
        f"Priority: {result.priority.priority.value}\nReason: {result.priority.explanation}\n\n"
        if result.priority
        else ""
    )
    return (
        f"{result.summary}\n\n"
        f"{priority_line}"
        f"Repository: {repository}\n\n"
        "Act on this signal report. Investigate the root cause, implement the fix, "
        "and open a PR if appropriate."
    )


def _select_opted_in_autostart_user(
    team_id: int,
    opted_in_user_ids: set[int],
    reviewers_content: list[ReviewerContent],
) -> User | None:
    login_to_user = get_org_member_github_login_to_user_map(team_id) or {}
    for reviewer in reviewers_content:
        candidate = login_to_user.get(reviewer["github_login"].lower())
        if isinstance(candidate, User) and candidate.id in opted_in_user_ids:
            return candidate
    return None


async def _maybe_autostart_task_for_report(
    team_id: int,
    report_id: str,
    repository: str,
    result: ReportResearchOutput,
    reviewers_content: list[ReviewerContent],
) -> None:
    if (
        result.actionability.actionability != ActionabilityChoice.IMMEDIATELY_ACTIONABLE
        or result.priority is None
        or not reviewers_content
        or await Task.objects.filter(signal_report_id=report_id).aexists()
    ):
        return

    team = await Team.objects.select_related("organization").aget(id=team_id)
    autonomy_config = await database_sync_to_async(get_or_create_team_extension, thread_sensitive=False)(
        team, SignalAutonomyConfig
    )

    if _priority_rank(result.priority.priority) > _priority_rank(Priority(autonomy_config.minimum_autostart_priority)):
        return

    opted_in_user_ids = set(autonomy_config.opted_in_user_ids or [])
    if not opted_in_user_ids:
        return

    task_user = await database_sync_to_async(_select_opted_in_autostart_user, thread_sensitive=False)(
        team_id, opted_in_user_ids, reviewers_content
    )
    if task_user is None:
        return

    task = await database_sync_to_async(Task.create_and_run, thread_sensitive=False)(
        team=team,
        title=result.title,
        description=_build_autostart_task_description(result, repository),
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        user_id=task_user.id,
        repository=repository,
        signal_report_id=report_id,
        posthog_mcp_scopes="full",
    )
    task_run = await task.runs.order_by("-created_at").afirst()
    if task_run is None:
        raise RuntimeError(f"Task {task.id} auto-started without producing a TaskRun")

    artefact_content: TaskRunArtefactContent = {
        "task_id": str(task.id),
        "task_run_id": str(task_run.id),
        "repository": repository,
        "title": task.title,
    }
    await SignalReportArtefact.objects.acreate(
        team_id=team_id,
        report_id=report_id,
        type=SignalReportArtefact.ArtefactType.TASK_RUN,
        content=json.dumps(artefact_content),
    )


def _replace_agentic_report_artefacts(
    team_id: int,
    report_id: str,
    artefacts: list[SignalReportArtefact],
) -> None:
    with transaction.atomic():
        # Delete artefacts from previous agentic runs (re-promotion) before writing new ones.
        # Only deletes types owned by this path — safety_judgment is created by the safety judge
        # activity and left untouched.
        SignalReportArtefact.objects.filter(
            team_id=team_id, report_id=report_id, type__in=_AGENTIC_ARTEFACT_TYPES
        ).delete()
        SignalReportArtefact.objects.bulk_create(artefacts)


async def _persist_agentic_report_artefacts(
    team_id: int, report_id: str, result: ReportResearchOutput, repo_selection: RepoSelectionResult
) -> None:
    artefacts: list[SignalReportArtefact] = [
        SignalReportArtefact(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
            content=repo_selection.model_dump_json(),
        ),
    ]
    artefacts.extend(
        SignalReportArtefact(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
            content=finding.model_dump_json(),
        )
        for finding in result.findings
    )
    artefacts.append(
        SignalReportArtefact(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=result.actionability.model_dump_json(),
        )
    )
    if result.priority:
        artefacts.append(
            SignalReportArtefact(
                team_id=team_id,
                report_id=report_id,
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content=result.priority.model_dump_json(),
            )
        )

    # Resolve suggested reviewers from commit hashes
    reviewers_content = await database_sync_to_async(_build_reviewers_content, thread_sensitive=False)(
        team_id=team_id,
        repository=repo_selection.repository or "",
        findings=result.findings,
    )
    if reviewers_content:
        artefacts.append(
            SignalReportArtefact(
                team_id=team_id,
                report_id=report_id,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                content=json.dumps(reviewers_content),
            )
        )

    await database_sync_to_async(_replace_agentic_report_artefacts, thread_sensitive=False)(
        team_id=team_id,
        report_id=report_id,
        artefacts=artefacts,
    )

    try:
        await _maybe_autostart_task_for_report(
            team_id=team_id,
            report_id=report_id,
            repository=repo_selection.repository or "",
            result=result,
            reviewers_content=reviewers_content,
        )
    except Exception as error:
        logger.exception(
            "signals auto-start task failed",
            report_id=report_id,
            team_id=team_id,
            repository=repo_selection.repository,
            error=str(error),
        )


@temporalio.activity.defn
async def run_agentic_report_activity(input: RunAgenticReportInput) -> RunAgenticReportOutput:
    """Run the sandbox-backed report research and persist its artefacts after full success."""
    try:
        # The workflow only calls this activity when repo_selection.repository is not None.
        assert input.repo_selection.repository is not None, "run_agentic_report_activity called without a repository"
        repository = input.repo_selection.repository

        async with Heartbeater():
            # 1. Get context for the sandbox
            user_id = await database_sync_to_async(resolve_user_id_for_team, thread_sensitive=False)(input.team_id)
            sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
                input.team_id, SIGNALS_REPORT_RESEARCH_ENV_NAME, SandboxEnvironment.NetworkAccessLevel.TRUSTED
            )
            context = CustomPromptSandboxContext(
                team_id=input.team_id,
                user_id=user_id,
                repository=repository,
                sandbox_environment_id=sandbox_env_id,
                posthog_mcp_scopes="read_only",  # Needs only read (queries, insights)
            )
            # 2. Load previous research if this is a re-promoted report
            previous_research = await _load_previous_research(input.report_id)
            # 3. Run the agentic research in the sandbox
            result = await run_multi_turn_research(
                input.signals,
                context,
                previous_report_id=input.report_id if previous_research else None,
                previous_report_research=previous_research,
                branch="master",
                signal_report_id=input.report_id,
            )
            # 4. Persist artefacts, avoid partial data from failed runs
            await _persist_agentic_report_artefacts(
                input.team_id,
                input.report_id,
                result,
                input.repo_selection,
            )
        logger.info(
            "signals agentic report completed",
            report_id=input.report_id,
            signal_count=len(input.signals),
            choice=result.actionability.actionability.value,
            repository=repository,
        )
        return RunAgenticReportOutput(
            title=result.title,
            summary=result.summary,
            choice=result.actionability.actionability,
            priority=result.priority.priority if result.priority else None,
            explanation=result.actionability.explanation,
            already_addressed=result.actionability.already_addressed,
            repository=repository,
        )
    except Exception as error:
        logger.exception(
            "signals agentic report failed",
            report_id=input.report_id,
            team_id=input.team_id,
            error=str(error),
        )
        raise
