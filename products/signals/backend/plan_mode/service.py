"""Plan mode write services: create a plan (report + planning conversation), assess readiness, and
finish a plan (defaults, owner scout, first implementation pass).

The plan lifecycle marker is the `safety_judgment` artefact: the planning flow never writes one, so
its absence means the plan is still a draft; `finish_plan` writes it (plans are user-driven, always
safe/actionable), making finish idempotent and letting the frontend derive draft-ness from artefacts
it already loads.
"""

from dataclasses import dataclass

import structlog

from posthog.models import Team, User

from products.signals.backend.artefact_schemas import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_PLANNING,
    ActionabilityAssessment,
    ActionabilityChoice,
    NoteArtefact,
    SafetyJudgment,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalScoutConfig
from products.signals.backend.plan_mode.prompts import (
    build_groundskeeping_note,
    build_owner_scout_body,
    build_owner_scout_description,
    build_owner_scout_display_name,
    build_planning_bootstrap_message,
)
from products.signals.backend.task_run_artefacts import append_task_run_artefact
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

# The artefacts (and report fields) a plan needs before it can be finished. Safety/actionability are
# deliberately absent — `finish_plan` writes those itself.
_REQUIRED_ARTEFACT_TYPES: dict[str, str] = {
    SignalReportArtefact.ArtefactType.REPO_SELECTION: "repository selection",
    SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS: "owners",
    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT: "priority",
}

OWNER_SCOUT_SKILL_PREFIX = "signals-scout-plan-"


class PlanNotReadyError(Exception):
    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Plan is missing: {', '.join(missing)}")


@dataclass(frozen=True)
class CreatedPlan:
    report_id: str
    task_id: str
    run_id: str | None


@dataclass(frozen=True)
class FinishedPlan:
    scout_skill_name: str
    # The auto-started first implementation pass; None when kickoff wasn't possible (e.g. no
    # resolvable owner) or the plan was already finished.
    implementation_task_id: str | None


@dataclass(frozen=True)
class PlanReadiness:
    ready: bool
    missing: list[str]
    finished: bool


def create_plan(*, team: Team, user: User, initial_description: str) -> CreatedPlan:
    """Create a draft plan report and start its interactive planning conversation.

    The report is born `READY` (like scout-authored reports — never touches the grouping pipeline)
    with no title yet and the user's initial description as the summary. The groundskeeping note is
    appended first so every later agent reads the contract, then the planning task boots repo-less
    (`repository=None`) — the agent asks the user which repos matter and clones them in-sandbox.
    """
    report = SignalReport.objects.create(
        team=team,
        status=SignalReport.Status.READY,
        title=None,
        summary=initial_description.strip() or None,
        signal_count=0,
        total_weight=0.0,
    )
    report_id = str(report.id)

    SignalReportArtefact.add_log(
        team_id=team.id,
        report_id=report_id,
        content=NoteArtefact(
            note=build_groundskeeping_note(report_id, owner_scout_skill_name(report_id)), author="plan mode"
        ),
        attribution=ArtefactAttribution.system(),
    )

    # Interactive runs only deliver `pending_user_message` to the agent — the task `description`
    # is UI metadata and never reaches the model. The first message is a short bootstrap (identity,
    # report id, hard rules, "read the groundskeeping note"); the full operating contract lives in
    # the groundskeeping note artefact above, which the agent is directed to fetch first.
    first_message = build_planning_bootstrap_message(report_id, initial_description)
    created = tasks_facade.create_and_run_task(
        team=team,
        title="Plan a new project",
        description=first_message,
        origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
        user_id=user.id,
        repository=None,
        create_pr=False,
        mode="interactive",
        signal_report_id=report_id,
        posthog_mcp_scopes="full",
        interaction_origin="signal_report",
        ai_stage="planning",
        pending_user_message=first_message,
    )
    run_id = str(created.latest_run.id) if created.latest_run else None
    append_task_run_artefact(
        team_id=team.id,
        report_id=report_id,
        product=SIGNALS_PRODUCT,
        type=TASK_RUN_TYPE_PLANNING,
        task_id=str(created.task_id),
        run_id=run_id,
    )

    logger.info("plan_mode.create_plan", extra={"team_id": team.id, "report_id": report_id})
    return CreatedPlan(report_id=report_id, task_id=str(created.task_id), run_id=run_id)


def plan_readiness(*, team_id: int, report: SignalReport) -> PlanReadiness:
    """What still blocks `finish_plan`. `finished` means the safety judgment already exists."""
    missing: list[str] = []
    if not (report.title or "").strip():
        missing.append("title")
    if not (report.summary or "").strip():
        missing.append("summary")

    present_types = set(
        SignalReportArtefact.objects.filter(report_id=report.id, type__in=_REQUIRED_ARTEFACT_TYPES.keys())
        .values_list("type", flat=True)
        .distinct()
    )
    missing.extend(label for t, label in _REQUIRED_ARTEFACT_TYPES.items() if t not in present_types)

    finished = SignalReportArtefact.objects.filter(
        report_id=report.id, type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT
    ).exists()
    return PlanReadiness(ready=not missing, missing=missing, finished=finished)


def finish_plan(*, team: Team, user: User, report: SignalReport) -> FinishedPlan:
    """Finalize a draft plan: write the user-driven defaults, create the owner scout, and auto-start
    the first implementation pass. No backing signal is emitted — plan reports live outside the
    grouping pipeline entirely (Plan tab membership is the Postgres planning marker), and the owner
    scout's sweep links related reports via `associated_report` artefacts. Idempotent — a plan that
    is already finished only converges the scout registration (no second implementation kickoff).
    """
    readiness = plan_readiness(team_id=team.id, report=report)
    if not readiness.ready:
        raise PlanNotReadyError(readiness.missing)

    report_id = str(report.id)
    attribution = ArtefactAttribution.from_user(user.id)

    if not readiness.finished:
        # Plans are user-driven: always safe and immediately actionable. reevaluate_autostart=False —
        # implementation kickoff is a deliberate step, not a side effect of finishing the plan.
        SignalReportArtefact.append_status(
            team_id=team.id,
            report_id=report_id,
            content=SafetyJudgment(choice=True, explanation=None),
            attribution=attribution,
            reevaluate_autostart=False,
        )
        SignalReportArtefact.append_status(
            team_id=team.id,
            report_id=report_id,
            content=ActionabilityAssessment(
                explanation="User-driven plan: finalized by its owner, actionable by definition.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            attribution=attribution,
            reevaluate_autostart=False,
        )
    skill_name = _ensure_owner_scout(team=team, user=user, report_id=report_id, title=report.title or "Untitled plan")

    # First implementation pass, without waiting for the owner scout's first activation (its cadence
    # is daily). Same path + in-flight guard as the scout's tool; only on the first finish, and
    # best-effort — a plan finishing must never fail because kickoff couldn't run (the scout picks
    # the work up on its next activation regardless).
    implementation_task_id: str | None = None
    if not readiness.finished:
        from products.signals.backend.scout_harness.tools.report import (  # noqa: PLC0415 — avoid circular import via scout harness
            start_implementation_for_report,
        )
        from products.signals.backend.scout_report.persistence import (  # noqa: PLC0415 — avoid circular import via scout harness
            InvalidScoutReportError,
        )

        try:
            started = start_implementation_for_report(
                team=team, report_id=report_id, triggered_by=f"plan_finish:{user.id}"
            )
            implementation_task_id = started.task_id
        except InvalidScoutReportError as exc:
            logger.warning(
                "plan_mode.finish_plan.implementation_kickoff_skipped",
                extra={"team_id": team.id, "report_id": report_id, "reason": str(exc)},
            )

    logger.info(
        "plan_mode.finish_plan",
        extra={
            "team_id": team.id,
            "report_id": report_id,
            "scout_skill_name": skill_name,
            "implementation_task_id": implementation_task_id,
        },
    )
    return FinishedPlan(scout_skill_name=skill_name, implementation_task_id=implementation_task_id)


def owner_scout_skill_name(report_id: str) -> str:
    # First UUID group is enough to be unique per project while keeping the name readable.
    return f"{OWNER_SCOUT_SKILL_PREFIX}{report_id.split('-')[0]}"


def _ensure_owner_scout(*, team: Team, user: User, report_id: str, title: str) -> str:
    """Create the plan's owner scout, or converge an existing skill of that name to the canonical
    template. The body is platform-owned — plan-specific steering lives in the plan's "Owner scout
    playbook" note, which the template instructs the scout to read — so a divergent body (e.g. one an
    agent authored) is overwritten rather than trusted; core behaviors must never drift.
    """
    skill_name = owner_scout_skill_name(report_id)
    expected_body = build_owner_scout_body(report_id, title)
    expected_description = build_owner_scout_description(title)
    expected_display_name = build_owner_scout_display_name(title)
    expected_tools = ["edit_report", "start_implementation"]

    skill = LLMSkill.objects.filter(team=team, name=skill_name, deleted=False, is_latest=True).first()
    if skill is None:
        LLMSkill.objects.create(
            team=team,
            name=skill_name,
            description=expected_description,
            body=expected_body,
            allowed_tools=expected_tools,
            metadata={
                "seeded_by": "signals_plan_mode",
                "report_id": report_id,
                "display_name": expected_display_name,
            },
            category="scout",
            version=1,
            is_latest=True,
        )
    elif (
        skill.body != expected_body
        or skill.allowed_tools != expected_tools
        or skill.category != "scout"
        or (skill.metadata or {}).get("display_name") != expected_display_name
    ):
        logger.warning(
            "plan_mode.owner_scout_converged_to_template",
            extra={"team_id": team.id, "report_id": report_id, "skill_name": skill_name},
        )
        skill.body = expected_body
        skill.description = expected_description
        skill.allowed_tools = expected_tools
        skill.category = "scout"
        skill.metadata = {
            **(skill.metadata or {}),
            "seeded_by": "signals_plan_mode",
            "report_id": report_id,
            "display_name": expected_display_name,
        }
        skill.save(update_fields=["body", "description", "allowed_tools", "category", "metadata"])
    SignalScoutConfig.all_teams.get_or_create(
        team=team,
        skill_name=skill_name,
        defaults={"enabled": True, "emit": True, "run_interval_minutes": 1440, "created_by": user},
    )
    return skill_name
