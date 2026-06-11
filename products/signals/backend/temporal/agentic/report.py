import json
from dataclasses import dataclass

from django.db import transaction

import structlog
import temporalio
import posthoganalytics
from pydantic import ValidationError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.auto_start import ReviewerContent, maybe_autostart_implementation_task
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    ReportResearchOutput,
    SignalFinding,
    run_multi_turn_research,
)
from products.signals.backend.report_generation.resolve_reviewers import resolve_suggested_reviewers
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.models import SandboxEnvironment
from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext

logger = structlog.get_logger(__name__)


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
    """Collect relevant commit SHAs from research findings and resolve them to GitHub reviewers.

    Deduplicates commit hashes across all findings (keeping the first reason seen per SHA),
    then calls resolve_suggested_reviewers to identify the authors/committers of those commits
    and returns them as serializable ReviewerContent dicts.

    The returned list is stored as a ``suggested_reviewers`` artefact keyed only by
    github_login — no PostHog user IDs are persisted. This is intentional:

    - PostHog user enrichment happens at read time (in the artefact serializer via
      ``enrich_reviewer_dicts_with_org_members``) so it stays fresh when users
      connect/disconnect their GitHub account.
    - The list view resolves ``is_suggested_reviewer`` by looking up the current
      user's GitHub login and checking for jsonb containment on ``github_login``
      in this artefact's content — no cached user IDs needed.
    """
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
        await maybe_autostart_implementation_task(
            team_id=team_id,
            report_id=report_id,
            repository=repo_selection.repository or "",
            title=result.title,
            summary=result.summary,
            actionability=result.actionability,
            priority=result.priority,
            reviewers_content=reviewers_content,
        )
    except Exception as error:
        posthoganalytics.capture_exception(error)
        logger.exception(
            "signals auto-start task failed",
            report_id=report_id,
            team_id=team_id,
            repository=repo_selection.repository,
            error=str(error),
        )


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
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
