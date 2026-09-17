"""The agent lane of a report check: dispatch a scout run, and wait for it to record a verdict.

A `metric_threshold` check is one query and one comparison, so the coordinator answers it in the
tick that collects it. Most of the inbox is not that shape. "Did the exception stop?" needs the
issue looked up, its recent events read, and the result weighed against what the fix changed, which
is a run rather than a comparison. This module is that second lane.

The split of responsibility is deliberate: this module only starts the run and records what came
back. It never decides the verdict, because the verdict is the run's whole job and the run is the
only thing that saw the evidence. A dispatch is therefore not a result, and the check stays active
with `dispatched_at` stamped until `scout-check-record-result` closes it or its window passes.

Most reports are pipeline-authored (error tracking, replay, and so on) and have no scout behind
them, so `skill_name` is optional: a check that names none runs on the fleet's follow-up scout.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from django.utils import timezone

import structlog
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportCheck, SignalScoutConfig
from products.signals.backend.report_checks import AgentCheckConfig, parse_check_config
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_run_in_flight, check_spend_gates
from products.signals.backend.scout_harness.team_limits import withheld_skills_for_team
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)

# The lane a check runs on when its author named no skill. The fleet's follow-up scout already
# exists to re-measure resolved reports, and it is an operational scout, so it is seeded enabled on
# every enrolled team and exempt from the inactivity sweep and the enabled-scout cap. A person can
# still pause it by hand, which the dispatch path reports as an errored run rather than working
# around.
FALLBACK_CHECK_SKILL_NAME = "signals-scout-inbox-validation"

# How long a dispatched run has to record its verdict before the coordinator gives up on it. A scout
# activity is killed at `WORKFLOW_HARD_CEILING_S` (16 minutes) and the coordinator ticks every 30,
# so two hours is several ticks past any run that is still alive. Sized generously because the cost
# of waiting too long is one late verdict, while the cost of waiting too little is a second run
# dispatched over the top of a live one.
AGENT_CHECK_RESULT_WINDOW = timedelta(hours=2)

# How long a check waits after a dispatch the fleet refused for a reason that passes on its own: a
# run of the same scout already in flight, a project at its daily run budget, a paused spend gate.
# Shorter than the errored-run retry because none of these says anything is wrong with the check.
CHECK_DISPATCH_DEFER_AFTER = timedelta(hours=1)

# Bounds on the brief the run is dispatched with. The note renders verbatim into the prompt, so the
# parts taken from the report (its title, and the note whoever resolved or dismissed it typed) are
# cut rather than trusted to be short.
MAX_CHECK_NOTE_REPORT_TITLE_LENGTH = 300
MAX_CHECK_NOTE_RESOLUTION_LENGTH = 1_000


@frozen
class CheckDispatchRefusal:
    """Why a check could not be dispatched this tick.

    `retryable` splits the two things a refusal can mean. A project at its daily run budget, or a
    lane already running, will be dispatchable again without anyone doing anything, so the check
    waits. A project not enrolled in scouts, or a lane a person paused, will not, so the check
    records an errored run: the report's log is where a reader finds out their follow-up never ran,
    and three of those retire the check instead of leaving it to expire in silence.
    """

    reason: str
    detail: str
    retryable: bool


def resolve_check_skill_name(config: AgentCheckConfig) -> str:
    return config.skill_name or FALLBACK_CHECK_SKILL_NAME


def _latest_resolution_note(report: SignalReport) -> str | None:
    """What the person who resolved or dismissed the report typed, when they typed anything.

    Both verbs write a `dismissal` artefact, so one read covers them. It is the highest-signal
    context a check run can get: the author of the check said what should hold, and this says what
    the person who closed the report believed they had done about it.
    """
    artefact = report.artefacts.filter(type=SignalReportArtefact.ArtefactType.DISMISSAL).order_by("-created_at").first()
    if artefact is None:
        return None
    try:
        content = json.loads(artefact.content)
    except (TypeError, ValueError):
        return None
    note = content.get("note") if isinstance(content, dict) else None
    return note.strip()[:MAX_CHECK_NOTE_RESOLUTION_LENGTH] if isinstance(note, str) and note.strip() else None


def build_check_run_note(check: SignalReportCheck, config: AgentCheckConfig) -> str:
    """The brief the dispatched run reads: what to establish, where to look, and how to answer.

    Composed here rather than in the prompt builder because every part of it except the tool name
    is untrusted content (the check's author wrote the instructions, a person typed the resolution
    note), and the prompt renders a run note inside the block it tells the agent to weigh rather
    than follow. The one trusted sentence, the instruction to close the check through
    `scout-check-record-result`, is repeated by the prompt's own check section, which is what the
    agent actually obeys.
    """
    lines = [
        "You were dispatched to answer one follow-up check on an inbox report.",
        "",
        f"- Check id: {check.id}",
        f"- Check: {check.title}",
    ]
    if check.rationale.strip():
        lines.append(f"- Why it was set: {check.rationale.strip()}")
    lines += [
        f"- Report: {(check.report.title or 'Untitled')[:MAX_CHECK_NOTE_REPORT_TITLE_LENGTH]} ({check.report_id})",
        f"- Report status: {check.report.status}",
    ]
    resolution_note = _latest_resolution_note(check.report)
    if resolution_note:
        lines.append(f"- What the person who closed the report wrote: {resolution_note}")
    lines += ["", "What to establish:", config.instructions]
    if config.probe_hints:
        lines += ["", "Where to look:"]
        lines += [f"- {hint}" for hint in config.probe_hints]
    lines += [
        "",
        f"Finish by calling `scout-check-record-result` with check_id `{check.id}` and an outcome of "
        "`passed` (the expectation still holds), `failed` (it does not), or `errored` (you could not "
        "establish either). That call is the only thing that closes the check.",
    ]
    return "\n".join(lines)


def _refuse_dispatch(skill_name: str, canonical_team_id: int) -> CheckDispatchRefusal | None:
    """The gates between a due check and a scout run, applied in order of cost.

    A check run is an ordinary scout run once it starts, so it honours every control the scheduled
    and manual paths honour (`run_gates`): the enrollment kill switch, the per-team daily run
    budget, the spend gates, and the single live run per lane. On top of those it needs a lane that
    can actually run, which the coordinator gets from the schedule and this path has to check for
    itself.
    """
    fleet_rejection = check_fleet_gates(canonical_team_id)
    if fleet_rejection is not None:
        # Not enrolled is permanent for this check's horizon; the daily budget is not.
        return CheckDispatchRefusal(
            reason=fleet_rejection.reason,
            detail=fleet_rejection.detail,
            retryable=fleet_rejection.reason != "not_enrolled",
        )

    if skill_name in withheld_skills_for_team(canonical_team_id):
        return CheckDispatchRefusal(
            reason="skill_withheld",
            detail=f"The `{skill_name}` scout is held back from this project, so the check could not run.",
            retryable=False,
        )

    config = SignalScoutConfig.all_teams.filter(team_id=canonical_team_id, skill_name=skill_name).first()
    if (
        config is None
        or not LLMSkill.objects.filter(
            team_id=canonical_team_id, name=skill_name, is_latest=True, deleted=False
        ).exists()
    ):
        return CheckDispatchRefusal(
            reason="scout_missing",
            detail=f"This project has no `{skill_name}` scout to run the check.",
            retryable=False,
        )
    # `enabled` is the same predicate the coordinator dispatches on, and every pause syncs it to
    # false, so it covers a human pause, a breaker trip, and the inactivity sweep alike. Reading
    # `status` instead would also refuse a `pending_pause` scout, which is warned but still running.
    if not config.enabled:
        return CheckDispatchRefusal(
            reason="scout_paused",
            detail=f"The `{skill_name}` scout is paused, so the check could not run.",
            retryable=False,
        )

    team = Team.objects.select_related("organization").get(pk=canonical_team_id)
    spend_rejection = check_spend_gates(team)
    if spend_rejection is not None:
        return CheckDispatchRefusal(reason=spend_rejection.reason, detail=spend_rejection.detail, retryable=True)

    in_flight = check_run_in_flight(canonical_team_id, skill_name)
    if in_flight is not None:
        return CheckDispatchRefusal(reason=in_flight.reason, detail=in_flight.detail, retryable=True)
    return None


def _claim_for_dispatch(check: SignalReportCheck, now: datetime) -> bool:
    """Stamp the check as dispatched, and say whether this caller is the one that stamped it.

    Written before the workflow starts, not after, because the run can reach
    `scout-check-record-result` before a post-start write commits, and that tool refuses a check no
    run is waiting on. The conditional update is also the concurrency guard: a check cancelled
    between collection and dispatch, or already claimed by an overlapping tick, matches nothing.
    """
    claimed = (
        SignalReportCheck.objects.for_team(check.team_id)
        .filter(id=check.id, status=SignalReportCheck.Status.ACTIVE, dispatched_at__isnull=True)
        .update(dispatched_at=now, next_run_at=now + AGENT_CHECK_RESULT_WINDOW, updated_at=now)
    )
    return bool(claimed)


def _release_dispatch_claim(check: SignalReportCheck, now: datetime) -> None:
    SignalReportCheck.objects.for_team(check.team_id).filter(id=check.id, dispatched_at__isnull=False).update(
        dispatched_at=None, next_run_at=now + CHECK_DISPATCH_DEFER_AFTER, updated_at=now
    )


def _defer(check: SignalReportCheck, now: datetime) -> None:
    """Push a check past a refusal that will clear on its own, without spending an error on it.

    Nothing bounds how often this can happen, and nothing needs to: `expires_at` is the check's
    horizon either way, so a project that stays throttled for the whole soak window retires the
    check as expired, which is the honest description of what happened.
    """
    SignalReportCheck.objects.for_team(check.team_id).filter(
        id=check.id, status=SignalReportCheck.Status.ACTIVE
    ).update(next_run_at=now + CHECK_DISPATCH_DEFER_AFTER, updated_at=now)


def run_agent_check(check: SignalReportCheck, *, now: datetime | None = None) -> str:
    """Advance one due `agent` check by one step. Returns `dispatched`, `deferred`, or `errored`.

    Never raises: like `measure_check`, a failure to dispatch is a verdict or a deferral, because a
    check that cannot report either way would head the due queue on every tick until its horizon.
    """
    # Deferred so the route-load path does not pay for the Signals Temporal workflow graph, which
    # this module reaches only when a check is actually due (see the same deferral in
    # `scout_harness/views.py`).
    from products.signals.backend.report_check_execution import CheckVerdict, record_check_verdict  # noqa: PLC0415
    from products.signals.backend.temporal.agentic.scout_scheduler import start_check_signals_scout_run  # noqa: PLC0415

    now = now or timezone.now()

    if check.dispatched_at is not None:
        # The window passed with the row still stamped, so the run this check was waiting on ended
        # without calling the tool: it crashed, ran out of budget, or finished on something else.
        # That is an errored run, so it retries on the next window and retires after three.
        logger.warning(
            "signals.report_check.agent_run_never_reported",
            check_id=str(check.id),
            team_id=check.team_id,
            dispatched_at=check.dispatched_at.isoformat(),
        )
        record_check_verdict(
            check,
            CheckVerdict(
                outcome="errored",
                explanation=f"{check.title} could not be checked: the follow-up run ended without recording a result.",
            ),
            now=now,
        )
        return "errored"

    try:
        config = parse_check_config(check.kind, check.config)
        assert isinstance(config, AgentCheckConfig)
    except Exception as error:
        logger.exception("signals.report_check.agent_config_invalid", check_id=str(check.id), team_id=check.team_id)
        record_check_verdict(
            check,
            CheckVerdict(outcome="errored", explanation=f"{check.title} could not be checked: {str(error)[:300]}"),
            now=now,
        )
        return "errored"

    skill_name = resolve_check_skill_name(config)
    # The scout fleet is bound to the canonical project, while the check sits on its report's own
    # environment team, so every gate and the dispatch itself resolve the parent.
    report_team = check.report.team
    canonical_team_id = report_team.parent_team_id or report_team.id

    try:
        refusal = _refuse_dispatch(skill_name, canonical_team_id)
    except Exception:
        # A gate that could not be resolved says nothing about the check, so it waits rather than
        # spending an error on a flag read or a row lookup that failed.
        logger.exception("signals.report_check.agent_gates_failed", check_id=str(check.id), team_id=check.team_id)
        _defer(check, now)
        return "deferred"
    if refusal is not None:
        logger.info(
            "signals.report_check.agent_dispatch_refused",
            check_id=str(check.id),
            team_id=check.team_id,
            skill_name=skill_name,
            reason=refusal.reason,
            retryable=refusal.retryable,
        )
        if refusal.retryable:
            _defer(check, now)
            return "deferred"
        record_check_verdict(
            check, CheckVerdict(outcome="errored", explanation=f"{check.title}: {refusal.detail}"), now=now
        )
        return "errored"

    if not _claim_for_dispatch(check, now):
        return "deferred"

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415 — keeps the Temporal client lazy

    try:
        workflow_id = start_check_signals_scout_run(
            sync_connect(),
            team_id=canonical_team_id,
            skill_name=skill_name,
            run_note=build_check_run_note(check, config),
        )
    except WorkflowAlreadyStartedError:
        # Another check on the same lane is still being answered. Theirs finishes, ours goes next
        # window; nothing is wrong with either check.
        _release_dispatch_claim(check, now)
        return "deferred"
    except Exception:
        logger.exception("signals.report_check.agent_dispatch_failed", check_id=str(check.id), team_id=check.team_id)
        _release_dispatch_claim(check, now)
        return "deferred"

    logger.info(
        "signals.report_check.agent_run_dispatched",
        check_id=str(check.id),
        team_id=check.team_id,
        skill_name=skill_name,
        workflow_id=workflow_id,
    )
    return "dispatched"
