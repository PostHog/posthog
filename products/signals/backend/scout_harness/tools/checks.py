"""The report-check tools a scout run holds: author one, read a report's, cancel one, close one.

`scout-check-record-result` is the one way a run closes the check it was dispatched to answer.
An `agent` check is dispatched as a scout run and stays open until this tool is called. Nothing
else closes it: the coordinator does not read the run's summary, and an agent that investigates and
then says nothing leaves a check its report can see is unanswered. That is deliberate. A verdict is
a claim recorded on the report, so it has to be a claim the run made on purpose.

The binding is what keeps the tool narrow. A run may only close a check that its own lane was
dispatched for and that is still waiting on a dispatch, so the broadest thing a compromised or
confused run can do is answer the question it was actually asked.

The authoring tools are the other direction: a run that surfaces something whose fix will show in
data writes the re-measurement down instead of leaving a note for a future run to find. They write
through `report_check_authoring`, so a scout-written check is the same row the REST endpoint writes
and obeys the same cap, the same metric-query copy, and the same bounds. Both are gated on the
report channel, because a check is a write on a report.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.db.models.functions import Coalesce

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportCheck, SignalScoutRun
from products.signals.backend.report_check_agent import resolve_check_skill_name
from products.signals.backend.report_check_authoring import CheckCreationError, cancel_check, create_check
from products.signals.backend.report_check_execution import CheckVerdict, record_check_verdict
from products.signals.backend.report_checks import AgentCheckConfig, parse_check_config
from products.signals.backend.scout_harness.tools.emit import _preflight_emit_gates, _resolve_task_id

MAX_CHECK_EXPLANATION_LENGTH = 1_000
# Rows one `scout-report-check-list` call returns. A report carries at most five open checks, so
# this only bounds the terminal ones a long-lived report accumulates.
MAX_CHECKS_LISTED = 50


class InvalidCheckResultError(ValueError):
    """A result a run may not record: an unknown check, someone else's, or one nothing is waiting on."""


class InvalidCheckWriteError(ValueError):
    """A check a run may not write, read, or cancel: an unknown report, or one outside its project."""


@frozen
class RecordCheckResultResult:
    check_id: str
    outcome: str
    # What the check became. A `passed` verdict on a recurring check leaves it `active` with runs
    # still owed, so the run can tell "answered, and we look again" from "answered, and that is it".
    check_status: str
    runs_remaining: int


def _resolve_dispatched_check(team: Team, run: SignalScoutRun, check_id: str) -> SignalReportCheck:
    """The check this run is allowed to close, or a refusal saying why it is not that check.

    Read through `all_teams` and scoped by hand, because a check sits on its report's own
    environment team while the run is resolved on the canonical project. Matching the canonical
    projects is the tenant boundary here: it admits a report on a child environment of the run's
    project and nothing outside it.
    """
    try:
        uuid.UUID(str(check_id))
    except (ValueError, TypeError):
        raise InvalidCheckResultError(f"check {check_id} not found")
    check = SignalReportCheck.all_teams.select_related("team__organization").filter(id=check_id).first()
    if check is None:
        raise InvalidCheckResultError(f"check {check_id} not found")
    canonical_team_id = team.parent_team_id or team.id
    if (check.team.parent_team_id or check.team_id) != canonical_team_id:
        raise InvalidCheckResultError(f"check {check_id} not found")
    if check.kind != SignalReportCheck.Kind.AGENT:
        raise InvalidCheckResultError(f"check {check_id} is a `{check.kind}` check, which the coordinator measures")
    if check.status != SignalReportCheck.Status.ACTIVE:
        raise InvalidCheckResultError(f"check {check_id} already finished as `{check.status}`")
    if check.dispatched_at is None:
        raise InvalidCheckResultError(f"check {check_id} is not waiting on a run, so it is not yours to close")

    config = parse_check_config(check.kind, check.config)
    assert isinstance(config, AgentCheckConfig)
    # Resolved with the project, exactly as the dispatch resolved it, so a run correctly sent to
    # the fallback lane because the named scout was retired can still record what it found.
    if resolve_check_skill_name(config, canonical_team_id) != run.skill_name:
        raise InvalidCheckResultError(f"check {check_id} runs on another scout")
    return check


def record_check_result(
    *,
    team: Team,
    run: SignalScoutRun,
    check_id: str,
    outcome: str,
    explanation: str,
    observed_value: float | None = None,
) -> RecordCheckResultResult:
    """Close one dispatched `agent` check with the verdict this run reached.

    The verdict goes through the executor's funnel, the same one the deterministic lane writes
    through, so an agent result advances or retires its check by exactly the rules a measured one
    does: a breach is terminal, an error retries and retires after three, and a pass re-arms a
    recurring check.
    """
    trimmed = explanation.strip()
    if not trimmed:
        raise InvalidCheckResultError("explanation must say what you established")
    if outcome not in {"passed", "failed", "errored"}:
        raise InvalidCheckResultError(f"outcome must be `passed`, `failed`, or `errored`, not `{outcome}`")

    check = _resolve_dispatched_check(team, run, check_id)
    record_check_verdict(
        check,
        CheckVerdict(
            outcome=outcome,  # type: ignore[arg-type]
            explanation=trimmed[:MAX_CHECK_EXPLANATION_LENGTH],
            # Only meaningful when the run measured something; an investigation that read a stack
            # trace has no number and says so by leaving it out.
            observed_value=observed_value,
        ),
        # Attributed to the run's task, the way every other artefact an agent writes is, so the
        # report's log names what produced the verdict rather than the system that scheduled it.
        attribution=_run_attribution(run),
        run_id=str(run.id),
    )
    check.refresh_from_db()
    return RecordCheckResultResult(
        check_id=str(check.id),
        outcome=outcome,
        check_status=check.status,
        runs_remaining=check.runs_remaining,
    )


@frozen
class ScoutCheckSummary:
    """One check, as a scout run reads it back."""

    check_id: str
    report_id: str
    title: str
    kind: str
    status: str
    next_run_at: datetime
    last_outcome: str | None


def _summarize(check: SignalReportCheck) -> ScoutCheckSummary:
    return ScoutCheckSummary(
        check_id=str(check.id),
        report_id=str(check.report_id),
        title=check.title,
        kind=check.kind,
        status=check.status,
        # Provisional on a pending check, whose clock the report's resolve starts.
        next_run_at=check.next_run_at,
        last_outcome=check.last_outcome,
    )


def _assert_run_may_write_checks(team: Team, run: SignalScoutRun) -> None:
    """Refuse a check write from a run whose other write channels are closed.

    A check is durable and later runs a query or starts a scout, so it follows the rule signals,
    reports and structured output follow: a dry-run scout previews what it would do and changes
    nothing, and a project without AI-processing consent gets no agent output.
    """
    skipped_reason = _preflight_emit_gates(team, run)
    if skipped_reason is not None:
        raise InvalidCheckWriteError(f"this run cannot write checks: {skipped_reason}")


def _resolve_report(team: Team, report_id: str) -> SignalReport:
    """The report a run may attach a check to, scoped the way `_resolve_dispatched_check` scopes a check.

    A report sits on its own environment team while the run is resolved on the canonical project, so
    the read matches canonical teams in the query: a report on a child environment of
    the run's project is reachable, and nothing outside it is.
    """
    try:
        uuid.UUID(str(report_id))
    except (ValueError, TypeError):
        raise InvalidCheckWriteError(f"report {report_id} not found")
    report = (
        SignalReport.objects.select_related("team")
        .alias(effective_project_id=Coalesce("team__parent_team_id", "team_id"))
        .filter(id=report_id, effective_project_id=team.parent_team_id or team.id)
        .exclude(status=SignalReport.Status.DELETED)
        .first()
    )
    if report is None:
        raise InvalidCheckWriteError(f"report {report_id} not found")
    return report


def create_report_check(
    *,
    team: Team,
    run: SignalScoutRun,
    report_id: str,
    title: str,
    kind: str,
    config: dict,
    rationale: str = "",
    next_run_at: datetime,
    expires_at: datetime,
    run_interval_minutes: int | None = None,
    runs_remaining: int = 1,
) -> ScoutCheckSummary:
    """Write one forward-looking check on a report this run can reach.

    Attributed to the run's task, like every other scout write, so the report's log names the run
    that decided the fix was worth re-measuring rather than the coordinator that will measure it.
    """
    _assert_run_may_write_checks(team, run)
    report = _resolve_report(team, report_id)
    try:
        check = create_check(
            report=report,
            title=title,
            rationale=rationale,
            kind=kind,
            config=config,
            attribution=_run_attribution(run),
            next_run_at=next_run_at,
            expires_at=expires_at,
            run_interval_minutes=run_interval_minutes,
            runs_remaining=runs_remaining,
        )
    except CheckCreationError as error:
        raise InvalidCheckWriteError(str(error)) from None
    return _summarize(check)


def list_report_checks(*, team: Team, report_id: str) -> list[ScoutCheckSummary]:
    """Every check on one report, newest first. Read it before writing: a report already carrying a
    check for the claim needs no second one, and the cap is five."""
    report = _resolve_report(team, report_id)
    checks = SignalReportCheck.objects.for_team(report.team_id).filter(report_id=report.id).order_by("-created_at")
    return [_summarize(check) for check in checks[:MAX_CHECKS_LISTED]]


def _run_attribution(run: SignalScoutRun) -> ArtefactAttribution:
    """Attribute a write to the run's task, the way every other scout write is attributed."""
    task_id = _resolve_task_id(run)
    return ArtefactAttribution.from_task(task_id) if task_id else ArtefactAttribution.system()


def cancel_report_check(*, team: Team, run: SignalScoutRun, check_id: str) -> ScoutCheckSummary:
    """Stop a check that is no longer worth running. Its recorded results stay on the report."""
    _assert_run_may_write_checks(team, run)
    try:
        uuid.UUID(str(check_id))
    except (ValueError, TypeError):
        raise InvalidCheckWriteError(f"check {check_id} not found")
    check = SignalReportCheck.all_teams.select_related("team").filter(id=check_id).first()
    if check is None:
        raise InvalidCheckWriteError(f"check {check_id} not found")
    canonical_team_id = team.parent_team_id or team.id
    if (check.team.parent_team_id or check.team_id) != canonical_team_id:
        raise InvalidCheckWriteError(f"check {check_id} not found")
    if not cancel_check(check, reason="stopped_by_scout", attribution=_run_attribution(run)):
        raise InvalidCheckWriteError(f"check {check_id} already finished as `{check.status}` and cannot be cancelled")
    return _summarize(check)
