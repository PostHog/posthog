"""Adoption telemetry for the forward-looking checks attached to signal reports.

Four events follow a check through its life. `signals_report_check_created` fires when an author
writes one. `signals_report_check_dispatch` fires each time the coordinator tries to hand an `agent`
check to a scout run, whether the run started or the attempt was deferred. `signals_report_check_evaluated`
fires for each verdict a run records. `signals_report_checks_expired` fires when checks retire at
their horizon without a verdict. Together they say how many reports get a check, which kind their
authors reach for, how long the soak window really is, how often a claim stops holding, and where a
check that never reported got stuck.

All are best-effort: telemetry must never fail the write it describes, so every call swallows its
own errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups

from products.signals.backend.models import SignalReportCheck

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)


def _metric_source(check: SignalReportCheck) -> str | None:
    """Where a `metric_threshold` check gets its number: a report metric, or the author's own query.

    Read off the stored config rather than parsed, because a config that stopped validating must
    still report what it was written as. An `agent` check measures nothing and reports nothing.
    """
    if check.kind != SignalReportCheck.Kind.METRIC_THRESHOLD:
        return None
    config = check.config or {}
    return "metric_id" if config.get("metric_id") else "query"


def _identity(team: Team, check: SignalReportCheck) -> dict[str, object]:
    """What both events say about the check they describe, so the two cannot drift apart."""
    return {
        "team_id": team.id,
        "organization_id": str(team.organization_id),
        "report_id": str(check.report_id),
        "check_id": str(check.id),
        "kind": check.kind,
        "metric_source": _metric_source(check),
    }


def capture_report_check_created(team: Team, check: SignalReportCheck) -> None:
    """`signals_report_check_created`: an author scheduled a re-measurement of a report's claim.

    `hours_to_first_run` and `hours_to_expiry` are the soak window the author chose, which is the
    number that says whether checks are being written for a real deploy-and-soak gap or for the
    default. A `pending` check has no clock yet, because it waits on its report resolving: its two
    hour values are provisional, and `soak_minutes` is the window its author chose. A null
    `run_interval_minutes` is a one-shot check.
    """
    try:
        now = timezone.now()
        posthoganalytics.capture(
            event="signals_report_check_created",
            distinct_id=str(team.uuid),
            properties={
                **_identity(team, check),
                "actor_kind": check.actor_kind,
                "actor_agent": check.actor_agent,
                "check_status": check.status,
                "soak_minutes": check.soak_minutes,
                "runs_remaining": check.runs_remaining,
                "run_interval_minutes": check.run_interval_minutes,
                "hours_to_first_run": (check.next_run_at - now).total_seconds() / 3600,
                "hours_to_expiry": (check.expires_at - now).total_seconds() / 3600,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("signals.report_check.created_capture_failed", check_id=str(check.id), team_id=check.team_id)


def capture_report_check_evaluated(team: Team, check: SignalReportCheck, *, run_id: str | None = None) -> None:
    """`signals_report_check_evaluated`: a run recorded a verdict on a check.

    Emitted per verdict rather than per check, so a recurring check that keeps holding reports one
    event each time it is measured. `check_status` says what the row became, so "answered, and that
    is it" (`passed`, `failed`, `errored`) reads apart from "answered, and we look again"
    (`active`).

    `run_id` names the scout run that decided an `agent` check. The deterministic lane has none,
    which is what tells the two lanes apart in the data. Requires `team.organization` to be loaded.
    """
    try:
        posthoganalytics.capture(
            event="signals_report_check_evaluated",
            distinct_id=str(team.uuid),
            properties={
                **_identity(team, check),
                "outcome": check.last_outcome,
                "check_status": check.status,
                "runs_remaining": check.runs_remaining,
                "consecutive_errors": check.consecutive_errors,
                "hours_since_created": (timezone.now() - check.created_at).total_seconds() / 3600,
                "run_id": run_id,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("signals.report_check.evaluated_capture_failed", check_id=str(check.id), team_id=check.team_id)


def capture_report_check_dispatch(
    team: Team, check: SignalReportCheck, *, outcome: str, skill_name: str | None = None, reason: str | None = None
) -> None:
    """`signals_report_check_dispatch`: the coordinator tried to hand an `agent` check to a scout run.

    `outcome` is `dispatched` or `deferred`. A deferral carries the `reason` the fleet refused the
    run, so a check that expires unanswered can be traced to the gate that held it. A refusal that
    cannot clear by itself is recorded as an errored verdict instead, and reports through
    `signals_report_check_evaluated`.
    """
    try:
        posthoganalytics.capture(
            event="signals_report_check_dispatch",
            distinct_id=str(team.uuid),
            properties={
                **_identity(team, check),
                "outcome": outcome,
                "skill_name": skill_name,
                "reason": reason,
                "hours_since_created": (timezone.now() - check.created_at).total_seconds() / 3600,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("signals.report_check.dispatch_capture_failed", check_id=str(check.id), team_id=check.team_id)


def capture_report_checks_expired(team: Team, *, expired_count: int, never_ran_count: int) -> None:
    """`signals_report_checks_expired`: checks on one project retired at their horizon.

    One event per project per sweep rather than one per check, because the sweep retires rows in
    bulk. `never_ran_count` is the part that matters: a check that expires with no run behind it
    was written and then never looked at.
    """
    try:
        posthoganalytics.capture(
            event="signals_report_checks_expired",
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "expired_count": expired_count,
                "never_ran_count": never_ran_count,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("signals.report_check.expired_capture_failed", team_id=team.id)
