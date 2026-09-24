"""The activity-log entries a `SignalReportCheck` leaves behind, other than its verdict.

Every writer lives here rather than at its call site, because a lifecycle entry is written from
four places — the shared authoring path, the expiry sweep, and the cancel paths — and they have to
agree on what an entry says. Each is best-effort: the transition has already happened, and losing
its log entry must not fail it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import structlog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckCancelled, CheckExpired, CheckScheduled
from products.signals.backend.models import SignalReportArtefact, SignalReportCheck

logger = structlog.get_logger(__name__)


def _write(
    check: SignalReportCheck,
    content: CheckScheduled | CheckExpired | CheckCancelled,
    attribution: ArtefactAttribution,
) -> None:
    try:
        SignalReportArtefact.add_log(
            team_id=check.team_id,
            report_id=str(check.report_id),
            content=content,
            attribution=attribution,
        )
    except Exception:
        logger.exception(
            "signals.report_check.lifecycle_artefact_failed",
            check_id=str(check.id),
            artefact_type=type(content).__name__,
        )


def _skill_name(check: SignalReportCheck) -> str | None:
    """The scout lane an `agent` check names, or null for the fleet's follow-up scout.

    Read off the stored config rather than parsed, so a config that stopped validating still says
    which lane its author chose.
    """
    if check.kind != SignalReportCheck.Kind.AGENT:
        return None
    skill_name = (check.config or {}).get("skill_name")
    return skill_name if isinstance(skill_name, str) else None


def write_check_scheduled(check: SignalReportCheck, attribution: ArtefactAttribution) -> None:
    """Record that a check now watches this report.

    A pending check gets this entry at creation and not a second one when the resolve arms it: the
    transition a reader cares about is that the watch exists, and `arms_on_resolve` already says the
    date is the resolve's to set. The live date belongs to the rail row, which reads the check.
    """
    _write(
        check,
        CheckScheduled(
            check_id=str(check.id),
            kind=check.kind,
            title=check.title,
            rationale=check.rationale,
            next_run_at=check.next_run_at.isoformat(),
            arms_on_resolve=check.status == SignalReportCheck.Status.PENDING,
            soak_minutes=check.soak_minutes,
            skill_name=_skill_name(check),
            runs=check.runs_remaining,
        ),
        attribution,
    )


def write_check_expired(check: SignalReportCheck, expired_at: datetime) -> None:
    """Record that a check reached its horizon without settling.

    Attributed to the system, because no author chose this: the sweep retires the row when its
    horizon passes.
    """
    _write(
        check,
        CheckExpired(
            check_id=str(check.id),
            kind=check.kind,
            title=check.title,
            expired_at=expired_at.isoformat(),
            last_run_at=check.last_run_at.isoformat() if check.last_run_at else None,
        ),
        ArtefactAttribution.system(),
    )


def write_check_cancelled(
    check: SignalReportCheck,
    *,
    reason: Literal["stopped_by_person", "stopped_by_scout", "replaced_by_research"],
    attribution: ArtefactAttribution,
) -> None:
    """Record that a check was stopped before it could decide.

    `reason` separates the three paths, because they mean different things to a reader: a person
    stopped watching, a scout run retired its own check, or a re-research pass replaced the check
    with one written against the report's new prose.
    """
    _write(
        check,
        CheckCancelled(check_id=str(check.id), kind=check.kind, title=check.title, reason=reason),
        attribution,
    )
