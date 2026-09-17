"""The one place a `SignalReportCheck` row is written, and the one place a pending check is armed.

Three callers author checks — the REST endpoint, the scout tool, and the research pipeline — and
they must agree on what a check row means, so the cap, the metric-query copy, and the attribution
live here rather than three times over. `report_checks.py` still owns the shapes and the bounds;
this module owns the write.

A check written after the fix shipped names the date to look on. A check written *before* it cannot:
the research turn authors its check in the same pass that writes the report, and many fixes never
get a merged pull request to date a soak window from. Such a check is stored `pending` with a soak
duration and armed by the report's transition to `resolved`, whatever caused it. That makes the
resolve the clock for every kind of fix.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

import structlog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportCheck
from products.signals.backend.report_check_execution import resolve_check_query
from products.signals.backend.report_checks import (
    DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
    MAX_ACTIVE_CHECKS_PER_REPORT,
    MAX_CHECK_HORIZON,
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

    Pass `next_run_at` and `expires_at` for a check that already knows when to look. Pass
    `soak_minutes` instead for one that waits on the report resolving; the row is stored `pending`
    and its dates are provisional until `arm_pending_checks` rewrites them.

    The report row is locked for the same reason the REST path locks it: the per-report cap is a
    count followed by an insert, which only holds if concurrent creates serialize.
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
    if soak_minutes is not None:
        status = SignalReportCheck.Status.PENDING
        # Provisional, and rewritten at arm time. The horizon is real though: a report that never
        # resolves retires its pending checks rather than holding them forever.
        next_run_at = now + timedelta(minutes=soak_minutes)
        expires_at = now + MAX_CHECK_HORIZON
    else:
        status = SignalReportCheck.Status.ACTIVE
        assert next_run_at is not None
        if expires_at is None:
            expires_at = min(
                _last_run_at(next_run_at, run_interval_minutes, runs_remaining) + DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
                now + MAX_CHECK_HORIZON,
            )

    with transaction.atomic():
        locked_report = SignalReport.objects.select_for_update().filter(id=report.id, team_id=report.team_id).first()
        if locked_report is None:
            raise CheckCreationError("The report this check belongs to is gone.")
        open_checks = SignalReportCheck.objects.for_team(locked_report.team_id).filter(
            report_id=locked_report.id, status__in=SignalReportCheck.OPEN_STATUSES
        )
        if open_checks.count() >= MAX_ACTIVE_CHECKS_PER_REPORT:
            raise CheckCreationError(f"A report may carry at most {MAX_ACTIVE_CHECKS_PER_REPORT} active checks.")
        return SignalReportCheck.objects.for_team(locked_report.team_id).create(
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


def create_checks_from_specs(
    *,
    report: SignalReport,
    specs: list[CheckSpec],
    attribution: ArtefactAttribution,
) -> list[SignalReportCheck]:
    """Write a research run's check specs on the report it just finished.

    A spec the report cannot carry is dropped with a log rather than failing the run, the way an
    unvalidatable chart is: the prose is the report's point, and a check that names a metric the
    presentation turn did not keep is the model over-reaching, not a broken pipeline.
    """
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


def _last_run_at(next_run_at: datetime, run_interval_minutes: int | None, runs_remaining: int) -> datetime:
    if not run_interval_minutes:
        return next_run_at
    return next_run_at + timedelta(minutes=run_interval_minutes * max(0, runs_remaining - 1))
