"""Create features, assess their planning readiness, and activate ongoing ownership.

The `safety_judgment` artefact marks completion of the initial planning phase. The feature itself
continues through implementation, release, monitoring, and optimization after that marker exists.
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
from products.signals.backend.features.prompts import (
    build_groundskeeping_note,
    build_owner_scout_body,
    build_owner_scout_description,
    build_owner_scout_display_name,
    build_planning_bootstrap_message,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalScoutConfig
from products.signals.backend.task_run_artefacts import append_task_run_artefact
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

# Planning needs these artefacts before it can complete. Safety and actionability are deliberately
# absent because the feature workflow writes those itself.
_REQUIRED_ARTEFACT_TYPES: dict[str, str] = {
    SignalReportArtefact.ArtefactType.REPO_SELECTION: "repository selection",
    SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS: "owners",
    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT: "priority",
}

OWNER_SCOUT_SKILL_PREFIX = "signals-scout-feature-"


class FeaturePlanningNotReadyError(Exception):
    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Feature planning is missing: {', '.join(missing)}")


@dataclass(frozen=True)
class CreatedFeature:
    report_id: str
    task_id: str
    run_id: str | None


@dataclass(frozen=True)
class FeaturePlanningCompletion:
    scout_skill_name: str
    # None when kickoff was not possible or planning had already been completed.
    implementation_task_id: str | None


@dataclass(frozen=True)
class FeaturePlanningReadiness:
    ready: bool
    missing: list[str]
    planning_finished: bool


def create_feature(*, team: Team, user: User, initial_description: str) -> CreatedFeature:
    """Create a feature report and start its interactive planning phase.

    The report is born `READY` and never touches the grouping pipeline. It starts without a title
    and uses the initial description as its summary. The groundskeeping note is appended first so
    every later agent reads the contract, then the planning task boots repo-less
    (`repository=None`) so the agent can ask which repositories matter and clone them for reference.
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
            note=build_groundskeeping_note(report_id, owner_scout_skill_name(report_id)),
            author="feature management",
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
        title="Plan a new feature",
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

    logger.info("feature_management.create_feature", extra={"team_id": team.id, "report_id": report_id})
    return CreatedFeature(report_id=report_id, task_id=str(created.task_id), run_id=run_id)


def feature_planning_readiness(*, team_id: int, report: SignalReport) -> FeaturePlanningReadiness:
    """Return what still blocks completion of the feature's planning phase."""
    missing: list[str] = []
    if not (report.title or "").strip():
        missing.append("title")
    if not (report.summary or "").strip():
        missing.append("summary")

    present_types = set(
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report.id,
            type__in=_REQUIRED_ARTEFACT_TYPES.keys(),
        )
        .values_list("type", flat=True)
        .distinct()
    )
    missing.extend(label for t, label in _REQUIRED_ARTEFACT_TYPES.items() if t not in present_types)

    planning_finished = SignalReportArtefact.objects.filter(
        team_id=team_id,
        report_id=report.id,
        type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
    ).exists()
    return FeaturePlanningReadiness(ready=not missing, missing=missing, planning_finished=planning_finished)


def finish_feature_planning(*, team: Team, user: User, report: SignalReport) -> FeaturePlanningCompletion:
    """Complete initial planning and activate the feature's owner scout and first implementation pass.

    Feature reports remain outside the grouping pipeline. Their owner scouts connect related reports
    with `associated_report` artefacts. Repeated calls converge the scout without starting another
    initial implementation pass.
    """
    readiness = feature_planning_readiness(team_id=team.id, report=report)
    if not readiness.ready:
        raise FeaturePlanningNotReadyError(readiness.missing)

    report_id = str(report.id)
    attribution = ArtefactAttribution.from_user(user.id)

    if not readiness.planning_finished:
        # User-created features are safe and immediately actionable once their owner completes
        # planning. Implementation kickoff remains an explicit workflow step below.
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
                explanation="User-created feature: planning completed by its owner.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            attribution=attribution,
            reevaluate_autostart=False,
        )
    skill_name = _ensure_owner_scout(
        team=team,
        user=user,
        report_id=report_id,
        title=report.title or "Untitled feature",
    )

    # Start the first pass without waiting for the daily owner scout activation. Kickoff is best
    # effort because the scout can retry it on its next activation.
    implementation_task_id: str | None = None
    if not readiness.planning_finished:
        from products.signals.backend.scout_harness.tools.report import (  # noqa: PLC0415 — avoid circular import via scout harness
            start_implementation_for_report,
        )
        from products.signals.backend.scout_report.persistence import (  # noqa: PLC0415 — avoid circular import via scout harness
            InvalidScoutReportError,
        )

        try:
            started = start_implementation_for_report(
                team=team,
                report_id=report_id,
                triggered_by=f"feature_planning_finished:{user.id}",
            )
            implementation_task_id = started.task_id
        except InvalidScoutReportError as exc:
            logger.warning(
                "feature_management.finish_feature_planning.implementation_kickoff_skipped",
                extra={"team_id": team.id, "report_id": report_id, "reason": str(exc)},
            )

    logger.info(
        "feature_management.finish_feature_planning",
        extra={
            "team_id": team.id,
            "report_id": report_id,
            "scout_skill_name": skill_name,
            "implementation_task_id": implementation_task_id,
        },
    )
    return FeaturePlanningCompletion(scout_skill_name=skill_name, implementation_task_id=implementation_task_id)


def owner_scout_skill_name(report_id: str) -> str:
    # First UUID group is enough to be unique per project while keeping the name readable.
    return f"{OWNER_SCOUT_SKILL_PREFIX}{report_id.split('-')[0]}"


def _ensure_owner_scout(*, team: Team, user: User, report_id: str, title: str) -> str:
    """Create the feature owner scout or converge it to the canonical behavior.

    Feature-specific steering lives in the report's owner scout playbook. The platform owns the
    core behavior so agents cannot accidentally remove monitoring or optimization responsibilities.
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
                "seeded_by": "signals_feature_management",
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
            "feature_management.owner_scout_converged_to_template",
            extra={"team_id": team.id, "report_id": report_id, "skill_name": skill_name},
        )
        skill.body = expected_body
        skill.description = expected_description
        skill.allowed_tools = expected_tools
        skill.category = "scout"
        skill.metadata = {
            **(skill.metadata or {}),
            "seeded_by": "signals_feature_management",
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
