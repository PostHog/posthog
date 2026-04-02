import json
from dataclasses import dataclass

from django.db import transaction

import structlog
import temporalio
from pydantic import ValidationError

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

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
from products.signals.backend.temporal.agentic import resolve_user_id_for_team
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

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


def _load_previous_research(report_id: str) -> ReportResearchOutput | None:
    """Reconstruct the previous report state."""
    report = SignalReport.objects.filter(id=report_id).only("title", "summary").first()
    if report is None or not report.title or not report.summary:
        logger.info(
            "load previous research: no report or missing title/summary, treating as first run",
            report_id=report_id,
            has_report=report is not None,
        )
        return None
    artefacts = list(
        SignalReportArtefact.objects.filter(
            report_id=report_id,
            # Only types we care about for the agentic report generation
            type__in=[
                SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
                SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            ],
        ).order_by("created_at")
    )
    findings: list[SignalFinding] = []
    actionability: ActionabilityAssessment | None = None
    priority: PriorityAssessment | None = None
    for artefact in artefacts:
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


def _resolve_and_build_reviewers_artefact(
    team_id: int,
    report_id: str,
    repository: str,
    findings: list[SignalFinding],
) -> SignalReportArtefact | None:
    """Resolve commit authors to suggested reviewers and build the artefact.

    Content is a plain list of GitHub-only reviewer dicts:
      [{"github_login": "...", "github_name": "...", "relevant_commits": [...]}, ...]

    PostHog user enrichment happens at read time (serializer) so it stays
    fresh when users connect/disconnect their GitHub account.

    The list view resolves is_suggested_reviewer by looking up the current
    user's GitHub login and checking for jsonb containment on github_login
    in this artefact's content — no cached user IDs needed.
    """
    commit_hashes_with_reasons: dict[str, str] = {}
    for finding in findings:
        for sha, reason in finding.relevant_commit_hashes.items():
            if sha and sha not in commit_hashes_with_reasons:
                commit_hashes_with_reasons[sha] = str(reason) if reason else ""

    if not commit_hashes_with_reasons or not repository:
        return None

    resolved = resolve_suggested_reviewers(team_id, repository, commit_hashes_with_reasons)
    if not resolved:
        return None

    content = [
        {
            "github_login": r.login.lower(),
            "github_name": r.name,
            "relevant_commits": [c.model_dump() for c in r.commits],
        }
        for r in resolved
    ]

    return SignalReportArtefact(
        team_id=team_id,
        report_id=report_id,
        type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        content=json.dumps(content),
    )


def _persist_agentic_report_artefacts(
    team_id: int, report_id: str, result: ReportResearchOutput, repo_selection: RepoSelectionResult
) -> None:
    artefacts = [
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
    reviewers_artefact = _resolve_and_build_reviewers_artefact(
        team_id=team_id,
        report_id=report_id,
        repository=repo_selection.repository or "",
        findings=result.findings,
    )
    if reviewers_artefact:
        artefacts.append(reviewers_artefact)

    with transaction.atomic():
        # Delete artefacts from previous agentic runs (re-promotion) before writing new ones.
        # Only deletes types owned by this path — safety_judgment is created by the safety judge
        # activity and left untouched.
        SignalReportArtefact.objects.filter(
            team_id=team_id, report_id=report_id, type__in=_AGENTIC_ARTEFACT_TYPES
        ).delete()
        SignalReportArtefact.objects.bulk_create(artefacts)


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
            context = CustomPromptSandboxContext(
                team_id=input.team_id,
                user_id=user_id,
                repository=repository,
            )
            # 2. Load previous research if this is a re-promoted report
            previous_research = await database_sync_to_async(_load_previous_research, thread_sensitive=False)(
                input.report_id
            )
            # 3. Run the agentic research in the sandbox
            result = await run_multi_turn_research(
                input.signals,
                context,
                previous_report_id=input.report_id if previous_research else None,
                previous_report_research=previous_research,
                branch="master",
            )
            # 4. Persist artefacts, avoid partial data from failed runs
            await database_sync_to_async(_persist_agentic_report_artefacts, thread_sensitive=False)(
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
