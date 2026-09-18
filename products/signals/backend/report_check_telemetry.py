"""Adoption telemetry for the forward-looking checks attached to signal reports.

Two events, one per end of a check's life: `signals_report_check_created` when an author schedules
a re-measurement, and `signals_report_check_resolved` when a run records the verdict. Together they
answer the only questions that say whether the follow-up loop is working — how many reports get a
check at all, which kind their authors reach for, how long the soak window really is, and how often
a claim stops holding.

Both are best-effort: telemetry must never fail the write it describes, so every call swallows its
own errors.

A check that retires unrun reports nothing here. `expire_overdue_checks` retires a batch in one
bounded UPDATE and holds no team, so counting those would cost a query per tick for an outcome that
is already the gap between the two events.
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
    default. A null `run_interval_minutes` is a one-shot check. Requires `team.organization` to be
    loaded.
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
                "runs_remaining": check.runs_remaining,
                "run_interval_minutes": check.run_interval_minutes,
                "hours_to_first_run": (check.next_run_at - now).total_seconds() / 3600,
                "hours_to_expiry": (check.expires_at - now).total_seconds() / 3600,
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.exception("signals.report_check.created_capture_failed", check_id=str(check.id), team_id=check.team_id)


def capture_report_check_resolved(team: Team, check: SignalReportCheck, *, run_id: str | None = None) -> None:
    """`signals_report_check_resolved`: a run recorded a verdict on a check.

    Emitted per verdict rather than per check, so a recurring check that keeps holding reports one
    event each time it is measured. `check_status` says what the row became, so "answered, and that
    is it" (`passed`, `failed`, `errored`) reads apart from "answered, and we look again"
    (`active`).

    `run_id` names the scout run that decided an `agent` check. The deterministic lane has none,
    which is what tells the two lanes apart in the data. Requires `team.organization` to be loaded.
    """
    try:
        posthoganalytics.capture(
            event="signals_report_check_resolved",
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
        logger.exception("signals.report_check.resolved_capture_failed", check_id=str(check.id), team_id=check.team_id)
