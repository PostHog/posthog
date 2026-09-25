"""The one place a `SignalReportCheck` row is written, and the one place a pending check is armed.

Three callers author checks — the REST endpoint, the scout tool, and the research pipeline — and
they must agree on what a check row means, so the cap, the metric-query copy, and the attribution
live here rather than three times over. `report_checks.py` still owns the shapes and the bounds;
this module owns the write.

The report's own state decides when a check first runs. A check on a resolved report names the date
to look on. A check on a report that is still open cannot: the fix it re-measures has not shipped,
and many fixes never get a merged pull request to date a soak window from. Such a check is stored
`pending` with a soak duration and armed by the report's transition to `resolved`, whatever caused
it. That makes the resolve the clock for every kind of fix.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from functools import partial
from typing import Literal

from django.db import transaction
from django.utils import timezone

import structlog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportCheck
from products.signals.backend.report_check_artefacts import write_check_cancelled, write_check_scheduled
from products.signals.backend.report_check_execution import resolve_check_query
from products.signals.backend.report_check_telemetry import capture_report_check_created
from products.signals.backend.report_checks import (
    DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
    MAX_ACTIVE_CHECKS_PER_REPORT,
    MAX_CHECK_HORIZON,
    MAX_CHECK_SOAK_HOURS,
    MIN_CHECK_SOAK_HOURS,
    CheckConfigValidationError,
    CheckSpec,
    MetricThresholdConfig,
    parse_check_config,
)

logger = structlog.get_logger(__name__)


class CheckCreationError(ValueError):
    """A check that cannot be written: a bad config, an unresolvable metric, or a full report."""


def create_check(
    *,
    report: SignalReport,
    title: str,
    rationale: str = "",
    kind: str,
    config: dict,
    attribution: ArtefactAttribution,
    next_run_at: datetime | None = None,
    soak_minutes: int | None = None,
    run_interval_minutes: int | None = None,
    runs_remaining: int = 1,
    expires_at: datetime | None = None,
) -> SignalReportCheck:
    """Write one check on a report, armed or pending.

    Pass `next_run_at` and `expires_at` for a check that names when to look. Pass `soak_minutes`
    instead for one that names how long to wait after the report resolves.

    Which of the two the row uses is the report's call, not the caller's. A report that has not
    resolved has no fix live yet, so a check on it is stored `pending` with a soak, and its dates
    stay provisional until `arm_pending_checks` rewrites them at the resolve. A dated check keeps
    the gap its author left as that soak. Only a resolved report takes a date as written.

    The report row is locked for the same reason the REST path locks it: the per-report cap is a
    count followed by an insert, which only holds if concurrent creates serialize. The status
    decision is read under the same lock, so a resolve landing mid-write either precedes the row
    or arms it.
    """
    if (next_run_at is None) == (soak_minutes is None):
        raise CheckCreationError("a check names either a next_run_at or a soak_minutes, not both and not neither")

    try:
        parsed = parse_check_config(kind, config)
    except CheckConfigValidationError as error:
        raise CheckCreationError(str(error)) from None

    stored_config = dict(config)
    if isinstance(parsed, MetricThresholdConfig) and parsed.metric_id is not None:
        if parsed.query is not None:
            raise CheckCreationError(
                "provide either metric_id or query, not both. The metric's query is copied onto the check."
            )
        # Resolved now and stored, rather than at each run: an unresolvable reference would
        # otherwise sit idle for the whole soak window before retiring, and one resolved late would
        # measure whatever the metric had become.
        try:
            stored_config["query"] = resolve_check_query(parsed, report)
        except ValueError as error:
            raise CheckCreationError(f"This check cannot run: {error}.") from None

    now = timezone.now()

    with transaction.atomic():
        locked_report = SignalReport.objects.select_for_update().filter(id=report.id, team_id=report.team_id).first()
        if locked_report is None:
            raise CheckCreationError("The report this check belongs to is gone.")
        open_checks = SignalReportCheck.objects.for_team(locked_report.team_id).filter(
            report_id=locked_report.id, status__in=SignalReportCheck.OPEN_STATUSES
        )
        if open_checks.count() >= MAX_ACTIVE_CHECKS_PER_REPORT:
            raise CheckCreationError(f"A report may carry at most {MAX_ACTIVE_CHECKS_PER_REPORT} active checks.")
        if locked_report.status == SignalReport.Status.RESOLVED:
            status = SignalReportCheck.Status.ACTIVE
            if next_run_at is None:
                assert soak_minutes is not None
                next_run_at = now + timedelta(minutes=soak_minutes)
            if expires_at is None:
                expires_at = min(
                    _last_run_at(next_run_at, run_interval_minutes, runs_remaining)
                    + DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
                    now + MAX_CHECK_HORIZON,
                )
        else:
            status = SignalReportCheck.Status.PENDING
            if soak_minutes is None:
                assert next_run_at is not None
                soak_minutes = _soak_from_first_run(next_run_at, now)
            # Provisional, and rewritten at arm time. The horizon is real though: a report that
            # never resolves retires its pending checks rather than holding them forever.
            next_run_at = now + timedelta(minutes=soak_minutes)
            expires_at = now + MAX_CHECK_HORIZON
        check = SignalReportCheck.objects.for_team(locked_report.team_id).create(
            # The report's own environment team, never a canonicalized one: the report's reads and
            # its artefact log filter by it.
            team_id=locked_report.team_id,
            report_id=locked_report.id,
            title=title,
            rationale=rationale,
            kind=kind,
            config=stored_config,
            status=status,
            next_run_at=next_run_at,
            soak_minutes=soak_minutes,
            run_interval_minutes=run_interval_minutes,
            runs_remaining=runs_remaining,
            expires_at=expires_at,
            actor_kind=attribution.kind,
            actor_agent=attribution.agent_name,
            created_by_id=attribution.user_id,
            task_id=attribution.task_id,
        )
        # In the same transaction as the row, so the log can never show a watch the report does not
        # carry, nor carry one the log never opened.
        write_check_scheduled(check, attribution)
        # Reported from the shared write so every author is counted: the REST endpoint, the scout
        # tool and the research pipeline. Post-commit, so a check the cap or a rollback rejected is
        # never counted as written.
        transaction.on_commit(partial(capture_report_check_created, report.team, check))
        return check


def create_checks_from_specs(
    *,
    report: SignalReport,
    specs: list[CheckSpec],
    attribution: ArtefactAttribution,
) -> list[SignalReportCheck]:
    """Write a research run's check specs on the report it just finished.

    The specs replace the report's pending checks rather than joining them. Every pending row on the
    report was written against an older version of this prose, which this pass has just rewritten.
    Left in place, those rows would fill the per-report cap, and the resolve would arm them against
    prose they were not written for. A pass that returns no specs leaves them alone, because
    the verification turn is best-effort and an empty result can be a failed turn.

    A spec the report cannot carry is dropped with a log rather than failing the run, the way an
    unvalidatable chart is: the prose is the report's point, and a check that names a metric the
    presentation turn did not keep is the model over-reaching, not a broken pipeline.
    """
    if not specs:
        return []
    # Only the pending rows, never a check the resolve already armed: this pass replaces prose that
    # has not been measured against yet.
    for replaced in SignalReportCheck.objects.for_team(report.team_id).filter(
        report_id=report.id, status=SignalReportCheck.Status.PENDING
    ):
        cancel_check(
            replaced,
            reason="replaced_by_research",
            attribution=attribution,
            from_statuses=(SignalReportCheck.Status.PENDING,),
        )
    written: list[SignalReportCheck] = []
    for spec in specs:
        try:
            written.append(
                create_check(
                    report=report,
                    title=spec.title,
                    rationale=spec.rationale,
                    kind=spec.kind,
                    config=spec.config,
                    attribution=attribution,
                    soak_minutes=spec.soak_hours * 60,
                )
            )
        except CheckCreationError as error:
            logger.warning(
                "signals.report_check.research_spec_dropped",
                report_id=str(report.id),
                team_id=report.team_id,
                kind=spec.kind,
                reason=str(error),
            )
    return written


def cancel_check(
    check: SignalReportCheck,
    *,
    reason: Literal["stopped_by_person", "stopped_by_scout", "replaced_by_research"],
    attribution: ArtefactAttribution,
    from_statuses: Sequence[str] = SignalReportCheck.OPEN_STATUSES,
) -> bool:
    """Stop one check and log it. Returns False when the check had already finished.

    One conditional update rather than a read and then a write: a verdict that lands in between
    leaves a result artefact, and an unconditional write would overwrite the status that artefact
    explains. The log entry follows the update rather than the intent, so a cancel that lost that
    race records nothing, and it is built from the row as it was, so the entry names the check that
    was stopped rather than the status it now holds.

    `check` is refreshed either way, because both callers report the status back to whoever asked.
    """
    cancelled = (
        SignalReportCheck.objects.for_team(check.team_id)
        .filter(id=check.id, status__in=from_statuses)
        .update(status=SignalReportCheck.Status.CANCELLED, updated_at=timezone.now())
    )
    if cancelled:
        write_check_cancelled(check, reason=reason, attribution=attribution)
    check.refresh_from_db()
    return bool(cancelled)


def arm_pending_checks(*, team_id: int, report_id: str | uuid.UUID, resolved_at: datetime) -> int:
    """Start the clock on a resolved report's pending checks. Returns how many were armed.

    Called from the report's `post_save` receiver, so every resolve path reaches it: the pull
    request merge webhook, a manual resolve in the inbox, and an MCP state write alike.

    Each row is armed individually rather than in one UPDATE, because `next_run_at` and `expires_at`
    are derived from the row's own soak and schedule.
    """
    pending = list(
        SignalReportCheck.objects.for_team(team_id).filter(report_id=report_id, status=SignalReportCheck.Status.PENDING)
    )
    horizon = resolved_at + MAX_CHECK_HORIZON
    armed = 0
    for check in pending:
        next_run_at = resolved_at + timedelta(minutes=check.soak_minutes or 0)
        expires_at = min(
            _last_run_at(next_run_at, check.run_interval_minutes, check.runs_remaining)
            + DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
            horizon,
        )
        armed += (
            SignalReportCheck.objects.for_team(team_id)
            .filter(id=check.id, status=SignalReportCheck.Status.PENDING)
            .update(
                status=SignalReportCheck.Status.ACTIVE,
                next_run_at=next_run_at,
                expires_at=expires_at,
                updated_at=resolved_at,
            )
        )
    return armed


def _soak_from_first_run(next_run_at: datetime, now: datetime) -> int:
    """The soak a dated check keeps when its report has not resolved yet.

    The author left a gap before the first run to allow for deploy and soak time, so that gap is
    what the check waits out once the report resolves, bounded by what a soak may be.
    """
    minutes = round((next_run_at - now).total_seconds() / 60)
    return max(MIN_CHECK_SOAK_HOURS * 60, min(minutes, MAX_CHECK_SOAK_HOURS * 60))


def _last_run_at(next_run_at: datetime, run_interval_minutes: int | None, runs_remaining: int) -> datetime:
    if not run_interval_minutes:
        return next_run_at
    return next_run_at + timedelta(minutes=run_interval_minutes * max(0, runs_remaining - 1))
