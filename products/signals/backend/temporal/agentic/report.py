from dataclasses import dataclass
from typing import Any, TypeVar

from django.conf import settings
from django.db import transaction

import structlog
import temporalio
import posthoganalytics
from pydantic import BaseModel, ValidationError

from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.business_knowledge.backend.logic import is_available_for_team
from products.signals.backend.agent_runtime import STEP_RESEARCH, resolve_agent_runtime
from products.signals.backend.artefact_schemas import (
    MAX_SUGGESTED_REVIEWERS,
    ArtefactContent,
    RelatedTo,
    SuggestedReviewers,
)
from products.signals.backend.auto_start import ReviewerContent, maybe_autostart_implementation_task
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.report_charts import ReportChart, chart_batch_error
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    ProposedReviewer,
    ReportResearchOutput,
    ReviewerCandidate,
    SignalFinding,
    run_multi_turn_research,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    commit_hashes_from_findings,
    get_org_member_github_login_to_user_map,
    resolve_suggested_reviewers,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.reviewer_corrections import ReviewerCorrection, recent_reviewer_corrections
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

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
    # Resolved chart payload for `SignalReport.charts`: the JSON set to store, `[]` to clear, or
    # `None` to leave the column untouched. Applied by the transition activity that writes the
    # matching title/summary, so charts and their prose land in one transaction. Defaults to `None`
    # (the safe skip value) so an older workflow history that predates this field replays cleanly.
    charts: list[dict[str, Any]] | None = None


_ArtefactContentT = TypeVar("_ArtefactContentT", bound=BaseModel)


def _parse_artefact_content(
    model_cls: type[_ArtefactContentT], artefact: SignalReportArtefact, report_id: str
) -> _ArtefactContentT:
    # These artefacts are written only by this pipeline from the current schemas, so a parse failure
    # is a bug on our side (corrupt content or an incompatible schema change) — fail loudly rather
    # than silently dropping prior research and degrading a re-promotion into a fresh run.
    try:
        return model_cls.model_validate_json(artefact.content)
    except ValidationError as error:
        raise ValueError(
            f"report {report_id}: {artefact.type} artefact {artefact.id} is incompatible with the "
            f"current {model_cls.__name__} schema"
        ) from error


async def _load_previous_research(report_id: str) -> ReportResearchOutput | None:
    """Reconstruct the previous report state."""
    report = await SignalReport.objects.filter(id=report_id).only("title", "summary", "charts").afirst()
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

    # Artefacts are append-only, so there may be several versions of each. Iterating in
    # ascending `created_at` order means the last value seen wins: judgments collapse to their
    # latest, and findings are keyed by `signal_id` so a re-researched signal supersedes its
    # prior version while distinct signals each keep an entry.
    findings_by_signal: dict[str, SignalFinding] = {}
    actionability: ActionabilityAssessment | None = None
    priority: PriorityAssessment | None = None

    async for artefact in artefacts_qs:
        match artefact.type:
            case SignalReportArtefact.ArtefactType.SIGNAL_FINDING:
                finding = _parse_artefact_content(SignalFinding, artefact, report_id)
                findings_by_signal[finding.signal_id] = finding
            case SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT:
                actionability = _parse_artefact_content(ActionabilityAssessment, artefact, report_id)
            case SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT:
                priority = _parse_artefact_content(PriorityAssessment, artefact, report_id)

    findings = list(findings_by_signal.values())
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
        # Shown to the re-research as the charts it may keep/refresh/drop. Parsed tolerantly: a stored
        # chart that no longer validates (a tightened schema, a legacy shape) is dropped from the
        # context rather than failing the run — the agent just won't be offered that one to re-send.
        charts=_parse_stored_charts(report.charts, report_id),
        # Reconstructed from already-persisted artefacts, so everything is "old" — a re-research that
        # reuses these writes nothing; only what it changes lands in new_artefacts.
        old_artefacts=[*findings, actionability, *([priority] if priority else [])],
    )


def _parse_stored_charts(raw: object, report_id: str) -> list[ReportChart]:
    """Best-effort parse of a report's stored `charts` JSON into `ReportChart`s, skipping bad rows."""
    if not isinstance(raw, list):
        return []
    parsed: list[ReportChart] = []
    for entry in raw:
        try:
            parsed.append(ReportChart.model_validate(entry))
        except ValidationError:
            logger.warning("skipping unparseable stored chart", report_id=report_id)
    return parsed


async def _load_resolved_report_context(team_id: int, report_id: str) -> tuple[str | None, str | None]:
    """Title/summary of the resolved report this one recurred from, if any.

    When a signal that would have grouped into an already-resolved report spawns a fresh report
    instead (resolved reports never reopen), the grouping pipeline links the two with symmetric
    `related_to` artefacts. The recurrence source is whichever linked report is resolved — handing it
    to the research agent lets it judge regression vs. new dimension vs. distinct.
    """
    related_ids: list[str] = []
    async for artefact in SignalReportArtefact.objects.filter(
        team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.RELATED_TO
    ).order_by("created_at"):
        try:
            related_ids.append(RelatedTo.model_validate_json(artefact.content).report_id)
        except ValidationError:
            continue
    if not related_ids:
        return None, None
    resolved = (
        await SignalReport.objects.filter(id__in=related_ids, team_id=team_id, status=SignalReport.Status.RESOLVED)
        .only("title", "summary")
        .order_by("-created_at")
        .afirst()
    )
    if resolved is None:
        return None, None
    return resolved.title, resolved.summary


_AGENTIC_ARTEFACT_TYPES = [
    SignalReportArtefact.ArtefactType.REPO_SELECTION,
    SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
    SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
    SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
]


@dataclass(frozen=True)
class ArtefactDraft:
    """An artefact pending append: its typed content (the row's type derives from the model
    class) and who produced it."""

    content: ArtefactContent
    attribution: ArtefactAttribution


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
    commit_hashes_with_reasons = commit_hashes_from_findings(findings)

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
                reason=None,
                # Pipeline reviewers are commit-authorship-derived, never owner-injected.
                is_skill_owner=False,
            )
        )
    return reviewers_content


def _reviewer_candidates_from_content(reviewers_content: list[ReviewerContent]) -> list[ReviewerCandidate]:
    """Shape deterministic reviewer content into the prompt-facing candidate type."""
    return [
        ReviewerCandidate(
            github_login=content["github_login"],
            github_name=content["github_name"],
            evidence=[reason for commit in content["relevant_commits"] if (reason := commit.get("reason"))],
        )
        for content in reviewers_content
    ]


def _reviewers_from_proposals(
    team_id: int,
    proposals: list[ProposedReviewer],
    deterministic: list[ReviewerContent],
    corrections: list[ReviewerCorrection],
) -> list[ReviewerContent]:
    """Validate the agent's reviewer picks against evidence and shape them for persistence.

    An agent-proposed login is kept only when something this pipeline can verify backs it: it came
    out of the deterministic ranking, it belongs to an org member with a linked GitHub identity, or
    it appears in the human correction history. Anything else is treated as a hallucination and
    dropped, so a made-up login can never route a report. Returns an empty list when nothing
    survives; the caller then falls back to the deterministic ranking.
    """
    if not proposals:
        return []

    deterministic_by_login = {content["github_login"]: content for content in deterministic}
    correction_logins = {
        login.strip().lower()
        for correction in corrections
        for login in (*correction.before, *correction.after)
        if login and login.strip()
    }
    member_map = get_org_member_github_login_to_user_map(team_id) or {}

    validated: list[ReviewerContent] = []
    seen: set[str] = set()
    for proposal in proposals:
        login = proposal.github_login.strip().lower().lstrip("@")
        if not login or login in seen:
            continue
        ranked = deterministic_by_login.get(login)
        member = member_map.get(login)
        if ranked is None and member is None and login not in correction_logins:
            logger.warning(
                "dropping agent-proposed reviewer with no supporting evidence",
                team_id=team_id,
                github_login=login,
            )
            continue
        seen.add(login)
        github_name = ranked["github_name"] if ranked else None
        if github_name is None and member is not None:
            github_name = f"{member.first_name} {member.last_name}".strip() or None
        validated.append(
            ReviewerContent(
                github_login=login,
                github_name=github_name,
                # Commit evidence carries over when the ranking also surfaced this person, so an
                # agent pick that agrees with blame keeps its clickable commit trail.
                relevant_commits=ranked["relevant_commits"] if ranked else [],
                reason=proposal.reason.strip(),
                is_skill_owner=False,
            )
        )
        if len(validated) >= MAX_SUGGESTED_REVIEWERS:
            break
    return validated


def _append_agentic_report_artefacts(*, team_id: int, report_id: str, artefacts: list[ArtefactDraft]) -> None:
    # Append-only: each (re-promotion) run adds a new version of its artefacts rather than
    # replacing the previous ones. The report's current judgments / repo selection / reviewers are
    # the latest row of each type; findings are keyed by `signal_id` (latest per signal wins).
    # Prior versions are intentionally retained as report-log history. `_AGENTIC_ARTEFACT_TYPES`
    # is kept as the documented set these versions belong to (and is asserted disjoint from the
    # log types in tests). Written through `SignalReportArtefact.append` (the single artefact
    # write path, routing each type to its append semantics) in one transaction; the caller
    # orchestrates auto-start explicitly, so appends opt out of the model's auto-start
    # re-evaluation hook.
    #
    # Charts are NOT written here: they are report content that must land in the same transaction as
    # the title/summary they illustrate, which a later activity writes (`mark_report_ready` /
    # `mark_report_pending_input`). The research activity only resolves the payload; see
    # `_resolve_report_charts_payload` and `RunAgenticReportOutput.charts`.
    with transaction.atomic():
        for draft in artefacts:
            SignalReportArtefact.append(
                team_id=team_id,
                report_id=report_id,
                content=draft.content,
                attribution=draft.attribution,
                reevaluate_autostart=False,
            )


def _resolve_report_charts_payload(
    charts: list[ReportChart], charts_enabled: bool, *, report_id: str, team_id: int
) -> list[dict[str, Any]] | None:
    """Resolve an authored chart set to what a report's `charts` column should become, or `None` to
    leave it untouched. The transition activity that writes the title/summary applies this atomically.

    Three cases, because the model's output is untrusted and the presentation `charts` field is optional:
    - a valid non-empty set → its JSON payload (replace the column).
    - not opted in, or an *empty* set → `None` (leave the column alone). An omitted key and a
      deliberate "drop everything" both arrive empty and are indistinguishable, so wiping
      user-visible charts on that ambiguity is refused — the pipeline never auto-clears to zero (a
      human can clear from the inbox).
    - a cap-busting set (too many, too large, or a duplicate id the agent produced) → `[]` (clear),
      so a stale set can't sit under the run's new summary; any `chart:` link then degrades to a label.
    """
    if not charts_enabled or not charts:
        return None
    batch_error = chart_batch_error(charts)
    if batch_error:
        logger.warning(
            "clearing report charts: %s", batch_error, report_id=report_id, team_id=team_id, chart_count=len(charts)
        )
        return []
    return [chart.model_dump(mode="json") for chart in charts]


async def _resolve_reviewers_content(
    team_id: int,
    repository: str,
    result: ReportResearchOutput,
    deterministic: list[ReviewerContent] | None,
    corrections: list[ReviewerCorrection],
) -> tuple[list[ReviewerContent], bool]:
    """The report's reviewer set, and whether the agent's reviewers-turn picks supplied it.

    ``deterministic`` is the ranking already computed mid-session for the reviewers turn (None
    when the turn didn't run or never reached the ranking hook); computing it here otherwise keeps
    the single GitHub-API resolution per run. Agent picks win when any survive validation; the
    deterministic ranking is the fallback, so reviewer resolution behaves exactly as before this
    turn existed whenever the agent proposes nothing usable.
    """
    if deterministic is None:
        deterministic = await database_sync_to_async(_build_reviewers_content, thread_sensitive=False)(
            team_id=team_id,
            repository=repository,
            findings=result.effective_findings(),
        )
    if result.suggested_reviewers:
        agent_reviewers = await database_sync_to_async(_reviewers_from_proposals, thread_sensitive=False)(
            team_id,
            result.suggested_reviewers,
            deterministic,
            corrections,
        )
        if agent_reviewers:
            return agent_reviewers, True
    return deterministic, False


async def _persist_agentic_report_artefacts(
    team_id: int,
    report_id: str,
    result: ReportResearchOutput,
    repo_selection: RepoSelectionResult,
    reviewers_content: list[ReviewerContent] | None = None,
    reviewers_from_agent: bool = False,
) -> None:
    # The activity resolves reviewers itself (it holds the mid-session ranking cache and the
    # correction history) and passes them in; the seed/ingest management commands rely on this
    # default to resolve deterministically from the fixture's findings.
    if reviewers_content is None:
        reviewers_content, reviewers_from_agent = await _resolve_reviewers_content(
            team_id,
            repo_selection.repository or "",
            result,
            None,
            [],
        )

    # Persist only what's new this run; values the agent confirmed unchanged keep their latest
    # persisted row. Deterministic reviewers are derived purely from findings, so they're only
    # re-persisted when at least one finding changed; agent-decided reviewers can also change on
    # unchanged findings (new correction precedent), so those persist whenever the agent decided.
    #
    # Attribution: the research findings / judgments / reviewers were produced by the research
    # sandbox agent, so they're attributed to its task. Repo selection has its own task when a
    # selection agent ran (N candidates); the 0/1-candidate shortcuts and reused selections fall
    # back to system. These activities run on the Temporal worker but only *persist* what the
    # sandbox agents produced.
    research_attribution = (
        ArtefactAttribution.from_task(result.research_task_id)
        if result.research_task_id
        else ArtefactAttribution.system()
    )
    repo_selection_attribution = (
        ArtefactAttribution.from_task(repo_selection.task_id)
        if repo_selection.task_id
        else ArtefactAttribution.system()
    )
    # Everything the run flagged as new gets persisted; the artefact type derives from each content
    # model.
    has_new_finding = any(isinstance(content, SignalFinding) for content in result.new_artefacts)

    artefacts = [
        ArtefactDraft(content=repo_selection, attribution=repo_selection_attribution),
        *(ArtefactDraft(content=content, attribution=research_attribution) for content in result.new_artefacts),
    ]
    if reviewers_content and (has_new_finding or reviewers_from_agent):
        artefacts.append(
            ArtefactDraft(
                content=SuggestedReviewers.model_validate(list(reviewers_content)),
                attribution=research_attribution,
            )
        )

    await database_sync_to_async(_append_agentic_report_artefacts, thread_sensitive=False)(
        team_id=team_id,
        report_id=report_id,
        artefacts=artefacts,
    )

    # Backfill the research task's title now that research has produced the report title. At
    # task-creation time the report has no title yet (research is what produces it), so the task
    # starts with a sandbox-prompt placeholder; relabel it "Research: <report title>".
    if result.research_task_id and result.title:
        await database_sync_to_async(tasks_facade.set_task_title, thread_sensitive=False)(
            result.research_task_id, team_id, f"Research: {result.title}"
        )

    try:
        await maybe_autostart_implementation_task(
            team_id=team_id,
            report_id=report_id,
            repository=repo_selection.repository or "",
            title=result.title,
            summary=result.summary,
            actionability=result.effective_actionability(),
            priority=result.effective_priority(),
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


def _team_has_business_knowledge(team_id: int) -> bool:
    """Flag + ready-sources check, evaluated fresh per run so a flag flip takes
    effect immediately. Fail open to False — research must not die on a flag-service
    hiccup; the agent just won't be told about the knowledge base this run."""
    try:
        team = Team.objects.get(id=team_id)
        return is_available_for_team(team)
    except Exception:
        logger.warning("business knowledge availability check failed", team_id=team_id, exc_info=True)
        return False


def _team_report_charts_enabled(team_id: int) -> bool:
    """Whether the research agent may attach charts to this team's reports.

    Gated by the `signals-report-charts` flag, org-keyed, evaluated fresh per run so a flip takes
    effect immediately. Off by default everywhere so this ships dark on the fleet-wide research path;
    on locally so `analyze_report` exercises it. Fails closed to False — a flag-service hiccup must
    not start charting reports on a team that isn't opted in."""
    if settings.DEBUG:
        return True
    try:
        team = Team.objects.get(id=team_id)
        return feature_enabled_or_false(
            "signals-report-charts",
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("report-charts availability check failed", team_id=team_id, exc_info=True)
        return False


def _team_agentic_reviewers_enabled(team_id: int) -> bool:
    """Whether the research agent decides this team's suggested reviewers (the reviewers turn).

    Gated by the `signals-agentic-reviewers` flag, org-keyed, evaluated fresh per run so a flip
    takes effect immediately. Off by default so this ships dark on the fleet-wide research path; on
    locally so `analyze_report` exercises it. Fails closed to False, which keeps the deterministic
    commit-authorship ranking as the reviewer source on a flag-service hiccup."""
    if settings.DEBUG:
        return True
    try:
        team = Team.objects.get(id=team_id)
        return feature_enabled_or_false(
            "signals-agentic-reviewers",
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("agentic-reviewers availability check failed", team_id=team_id, exc_info=True)
        return False


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
                input.team_id, SIGNALS_REPORT_RESEARCH_ENV_NAME, tasks_facade.SandboxNetworkAccessLevel.TRUSTED
            )
            agent_runtime = await database_sync_to_async(resolve_agent_runtime, thread_sensitive=False)(
                input.team_id, STEP_RESEARCH
            )
            context = CustomPromptSandboxContext(
                team_id=input.team_id,
                user_id=user_id,
                repository=repository,
                sandbox_environment_id=sandbox_env_id,
                # Reads only: the research agent queries data/insights and can list the report's
                # artefacts, but never writes artefacts itself — the pipeline persists its
                # structured outputs after the session.
                posthog_mcp_scopes="read_only",
                model=agent_runtime.model,
                runtime_adapter=agent_runtime.runtime_adapter,
                reasoning_effort=agent_runtime.reasoning_effort,
            )
            has_bk = await database_sync_to_async(_team_has_business_knowledge, thread_sensitive=False)(input.team_id)
            charts_enabled = await database_sync_to_async(_team_report_charts_enabled, thread_sensitive=False)(
                input.team_id
            )
            agentic_reviewers = await database_sync_to_async(_team_agentic_reviewers_enabled, thread_sensitive=False)(
                input.team_id
            )
            corrections: list[ReviewerCorrection] = []
            if agentic_reviewers:
                corrections = await database_sync_to_async(recent_reviewer_corrections, thread_sensitive=False)(
                    input.team_id
                )

            # The reviewers turn asks for the deterministic ranking mid-session (it needs the
            # findings, which only exist then). The closure caches the result so the post-session
            # reviewer resolution reuses it instead of repeating the GitHub API lookups.
            deterministic_reviewers: list[ReviewerContent] | None = None

            async def _rank_reviewer_candidates(findings: list[SignalFinding]) -> list[ReviewerCandidate]:
                nonlocal deterministic_reviewers
                deterministic_reviewers = await database_sync_to_async(
                    _build_reviewers_content, thread_sensitive=False
                )(
                    team_id=input.team_id,
                    repository=repository,
                    findings=findings,
                )
                return _reviewer_candidates_from_content(deterministic_reviewers)

            # 2. Load previous research if this is a re-promoted report
            previous_research = await _load_previous_research(input.report_id)
            # 2b. Load the resolved report this one recurred from, if any, as extra research context
            resolved_report_title, resolved_report_summary = await _load_resolved_report_context(
                input.team_id, input.report_id
            )
            # 3. Run the agentic research in the sandbox
            result = await run_multi_turn_research(
                input.signals,
                context,
                previous_report_id=input.report_id if previous_research else None,
                previous_report_research=previous_research,
                signal_report_id=input.report_id,
                has_business_knowledge=has_bk,
                resolved_report_title=resolved_report_title,
                resolved_report_summary=resolved_report_summary,
                charts_enabled=charts_enabled,
                suggest_reviewers=agentic_reviewers,
                reviewer_corrections=corrections,
                rank_reviewer_candidates=_rank_reviewer_candidates if agentic_reviewers else None,
            )
            # 4. Resolve the reviewer set (agent picks when validated, deterministic otherwise),
            #    then persist artefacts, avoiding partial data from failed runs
            reviewers_content, reviewers_from_agent = await _resolve_reviewers_content(
                input.team_id,
                repository,
                result,
                deterministic_reviewers,
                corrections,
            )
            logger.info(
                "signals reviewers resolved",
                report_id=input.report_id,
                team_id=input.team_id,
                source="agent" if reviewers_from_agent else "deterministic",
                reviewer_count=len(reviewers_content),
                proposed_count=len(result.suggested_reviewers),
                agentic_reviewers_enabled=agentic_reviewers,
            )
            await _persist_agentic_report_artefacts(
                input.team_id,
                input.report_id,
                result,
                input.repo_selection,
                reviewers_content,
                reviewers_from_agent,
            )
        actionability = result.effective_actionability()
        priority = result.effective_priority()
        # Resolve the charts payload here, but let the transition activity write it alongside the
        # title/summary so charts and their prose land in one transaction (and never on the
        # not-actionable reset or a failed run, which don't write the new prose).
        charts_payload = _resolve_report_charts_payload(
            result.charts, charts_enabled, report_id=input.report_id, team_id=input.team_id
        )
        logger.info(
            "signals agentic report completed",
            report_id=input.report_id,
            signal_count=len(input.signals),
            choice=actionability.actionability.value,
            repository=repository,
        )
        return RunAgenticReportOutput(
            title=result.title,
            summary=result.summary,
            choice=actionability.actionability,
            priority=priority.priority if priority else None,
            explanation=actionability.explanation,
            already_addressed=actionability.already_addressed,
            repository=repository,
            charts=charts_payload,
        )
    except Exception as error:
        logger.exception(
            "signals agentic report failed",
            report_id=input.report_id,
            team_id=input.team_id,
            error=str(error),
        )
        raise
