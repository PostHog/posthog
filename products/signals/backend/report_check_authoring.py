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

from posthog.dataclasses import frozen

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportCheck
from products.signals.backend.report_check_artefacts import write_check_cancelled, write_check_scheduled
from products.signals.backend.report_check_execution import resolve_check_query
from products.signals.backend.report_check_research import research_can_reconcile_checks
from products.signals.backend.report_check_telemetry import capture_report_check_created
from products.signals.backend.report_check_timing import metric_check_ready_at
from products.signals.backend.report_checks import (
    DEFAULT_CHECK_SOAK_HOURS,
    MAX_ACTIVE_CHECKS_PER_REPORT,
    MAX_CHECK_HORIZON,
    CheckConfigValidationError,
    CheckSpec,
    MetricThresholdConfig,
    check_schedule_expires_at,
    parse_check_config,
    soak_minutes_from_gap,
    validate_metric_check_for_write,
)
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy

logger = structlog.get_logger(__name__)

_METRIC_DISPLAY_FIELDS = frozenset({"metric_kind", "value_format", "unit"})


class CheckCreationError(ValueError):
    """A check that cannot be written: a bad config, an unresolvable metric, or a full report."""


class CheckQueryAccessError(PermissionError):
    """The requester cannot read the measurement they would schedule."""


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

    stored_config = _stored_config(report, kind, config)

    now = timezone.now()

    with transaction.atomic():
        locked_report = SignalReport.objects.select_for_update().filter(id=report.id, team_id=report.team_id).first()
        if locked_report is None:
            raise CheckCreationError("The report this check belongs to is gone.")
        if soak_minutes is None:
            assert next_run_at is not None
            soak_minutes = soak_minutes_from_gap(next_run_at, now)
        first_run_at = (
            next_run_at
            if next_run_at is not None and locked_report.status == SignalReport.Status.RESOLVED
            else now + timedelta(minutes=soak_minutes)
        )
        metric_ready_at = None
        if kind == SignalReportCheck.Kind.METRIC_THRESHOLD:
            metric_ready_at = metric_check_ready_at(stored_config["query"], locked_report.team, now)
            first_run_at = max(first_run_at, metric_ready_at)
            last_run_at = first_run_at + timedelta(minutes=(run_interval_minutes or 0) * max(0, runs_remaining - 1))
            if last_run_at >= now + MAX_CHECK_HORIZON:
                raise CheckCreationError(
                    "The remaining runs must fit within the check's 90-day horizon. Use a shorter query window."
                )
        open_checks = SignalReportCheck.objects.for_team(locked_report.team_id).filter(
            report_id=locked_report.id, status__in=SignalReportCheck.OPEN_STATUSES
        )
        if open_checks.count() >= MAX_ACTIVE_CHECKS_PER_REPORT:
            raise CheckCreationError(f"A report may carry at most {MAX_ACTIVE_CHECKS_PER_REPORT} active checks.")
        if locked_report.status == SignalReport.Status.RESOLVED:
            status = SignalReportCheck.Status.ACTIVE
            next_run_at = first_run_at
            if metric_ready_at is not None:
                if expires_at is not None and expires_at <= next_run_at:
                    raise CheckCreationError("The expiry must allow a full post-resolution measurement window.")
            if expires_at is None:
                expires_at = check_schedule_expires_at(
                    next_run_at=next_run_at,
                    run_interval_minutes=run_interval_minutes,
                    runs_remaining=runs_remaining,
                    start_at=now,
                )
        else:
            status = SignalReportCheck.Status.PENDING
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
            measurement_start_at=now
            if status == SignalReportCheck.Status.ACTIVE and metric_ready_at is not None
            else None,
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


def _stored_config(report: SignalReport, kind: str, config: dict) -> dict:
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
        # The query comes from the named metric, so its display fields do too. Values the caller
        # sends could draw that query with another metric's format or unit.
        stored_config = _with_metric_display(
            report,
            {key: value for key, value in stored_config.items() if key not in _METRIC_DISPLAY_FIELDS},
            parsed.metric_id,
        )
        try:
            parse_check_config(kind, stored_config)
        except CheckConfigValidationError as error:
            raise CheckCreationError(str(error)) from None

    if isinstance(parsed, MetricThresholdConfig):
        stored_config = _with_metric_display(report, stored_config, parsed.metric_id)
        try:
            normalized = parse_check_config(kind, stored_config)
            assert isinstance(normalized, MetricThresholdConfig)
            validate_metric_check_for_write(normalized)
        except CheckConfigValidationError as error:
            raise CheckCreationError(str(error)) from None
    return stored_config


def _with_metric_display(report: SignalReport, config: dict, metric_id: str | None) -> dict:
    """Fill a metric check's display fields from the report metric it names, keeping any it already has."""
    filled = dict(config)
    for metric in report.metrics or []:
        if isinstance(metric, dict) and metric.get("metric_id") == metric_id:
            filled.setdefault("metric_kind", metric.get("kind", "custom"))
            filled.setdefault("value_format", metric.get("value_format", "number"))
            filled.setdefault("unit", metric.get("unit"))
            break
    if "comparison" in filled:
        filled["metric_kind"] = filled.get("metric_kind") or "custom"
        filled["value_format"] = filled.get("value_format") or "number"
        filled.setdefault("unit", None)
    return filled


def _check_configs_match(report: SignalReport, check: SignalReportCheck, desired: dict) -> bool:
    try:
        stored = parse_check_config(
            check.kind, _with_metric_display(report, check.config, check.config.get("metric_id"))
        )
    except CheckConfigValidationError:
        return False
    return stored == parse_check_config(check.kind, desired)


@frozen
class CheckReconciliation:
    applied: bool
    created: list[SignalReportCheck]


def create_checks_from_specs(
    *,
    report: SignalReport,
    specs: list[CheckSpec],
    attribution: ArtefactAttribution,
    checks_snapshot: dict[str, str] | None = None,
    reconcile: bool = True,
) -> CheckReconciliation:
    """Reconcile a successful verification turn with the report's open checks.

    Identical rows keep their schedule, results, and approval. A changed or omitted claim retires;
    replacements start unapproved. If a new spec cannot be stored, the transaction rolls back and
    leaves the old checks running.
    """
    try:
        with transaction.atomic():
            report = SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
            desired = [(spec, _stored_config(report, spec.kind, spec.config)) for spec in specs]
            existing = list(
                SignalReportCheck.objects.for_team(report.team_id)
                .select_for_update()
                .filter(report_id=report.id, status__in=SignalReportCheck.OPEN_STATUSES)
                .order_by("id")
            )
            if reconcile and not research_can_reconcile_checks(existing, checks_snapshot):
                logger.info(
                    "signals.report_check.research_reconciliation_skipped",
                    report_id=str(report.id),
                    team_id=report.team_id,
                    reason="checks_changed_during_research",
                    spec_count=len(specs),
                )
                return CheckReconciliation(applied=False, created=[])
            if not reconcile:
                existing = [
                    check
                    for check in existing
                    if check.status == SignalReportCheck.Status.PENDING
                    and check.actor_kind not in (SignalActorKind.USER, SignalActorKind.AGENT)
                    and check.approved_at is None
                ]
            retained_ids: set[uuid.UUID] = set()
            new_specs: list[tuple[CheckSpec, SignalReportCheck | None]] = []
            referenced_ids: set[uuid.UUID] = set()
            for spec, config in desired:
                previous = next((check for check in existing if check.id == spec.existing_check_id), None)
                if spec.existing_check_id is not None:
                    if previous is None or previous.id in referenced_ids or previous.id in retained_ids:
                        raise CheckCreationError("An existing check must be open on this report and referenced once.")
                    referenced_ids.add(previous.id)
                match = next(
                    (
                        check
                        for check in existing
                        if check.id not in retained_ids
                        and (check.id not in referenced_ids or check.id == spec.existing_check_id)
                        and (previous is None or check.id == previous.id)
                        and check.title == spec.title
                        and check.rationale == spec.rationale
                        and check.kind == spec.kind
                        and (
                            "soak_hours" not in spec.model_fields_set
                            or max(1, round((check.soak_minutes or 60) / 60)) == spec.soak_hours
                        )
                        and _check_configs_match(report, check, config)
                    ),
                    None,
                )
                if match is None:
                    new_specs.append((spec, previous))
                else:
                    retained_ids.add(match.id)
            for replaced in existing:
                if replaced.id not in retained_ids:
                    cancel_check(replaced, reason="replaced_by_research", attribution=attribution)
            created = [
                create_check(
                    report=report,
                    title=spec.title,
                    rationale=spec.rationale,
                    kind=spec.kind,
                    config=spec.config,
                    attribution=attribution,
                    soak_minutes=(
                        previous.soak_minutes if previous.soak_minutes is not None else DEFAULT_CHECK_SOAK_HOURS * 60
                    )
                    if previous is not None
                    and (
                        "soak_hours" not in spec.model_fields_set
                        or spec.soak_hours == max(1, round((previous.soak_minutes or 60) / 60))
                    )
                    else spec.soak_hours * 60,
                    run_interval_minutes=previous.run_interval_minutes if previous is not None else None,
                    runs_remaining=previous.runs_remaining if previous is not None else 1,
                )
                for spec, previous in new_specs
            ]
            return CheckReconciliation(applied=True, created=created)
    except (CheckCreationError, CheckConfigValidationError) as error:
        logger.warning(
            "signals.report_check.research_spec_dropped",
            report_id=str(report.id),
            team_id=report.team_id,
            reason=str(error) if isinstance(error, CheckCreationError) else "invalid_check_config",
        )
        return CheckReconciliation(applied=False, created=[])


def replace_metric_check(
    *,
    check: SignalReportCheck,
    title: str,
    rationale: str,
    config: dict,
    attribution: ArtefactAttribution,
    access_policy: ReportMetricAccessPolicy,
) -> SignalReportCheck:
    """Replace one open metric check atomically, keeping it live if the new check is invalid."""
    if check.kind != SignalReportCheck.Kind.METRIC_THRESHOLD:
        raise CheckCreationError("Only metric checks can be replaced this way.")
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(id=check.report_id, team_id=check.team_id)
        locked = SignalReportCheck.objects.for_team(check.team_id).select_for_update().get(id=check.id)
        if locked.report_id != report.id:
            raise CheckCreationError("This check moved to another report. Reload the report before replacing it.")
        stored_config = _stored_config(report, SignalReportCheck.Kind.METRIC_THRESHOLD, config)
        if not access_policy.may_read_query(stored_config):
            raise CheckQueryAccessError("The measurement query is not available to you.")
        if not cancel_check(locked, reason="replaced_by_request", attribution=attribution):
            raise CheckCreationError("This check has already finished. Review its result before adding another.")
        return create_check(
            report=report,
            title=title,
            rationale=rationale,
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            config=config,
            attribution=attribution,
            soak_minutes=locked.soak_minutes if locked.soak_minutes is not None else DEFAULT_CHECK_SOAK_HOURS * 60,
            run_interval_minutes=locked.run_interval_minutes,
            runs_remaining=locked.runs_remaining,
        )


def cancel_check(
    check: SignalReportCheck,
    *,
    reason: Literal["stopped_by_person", "stopped_by_scout", "replaced_by_research", "replaced_by_request"],
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
        SignalReportCheck.objects.for_team(team_id)
        .filter(report_id=report_id, status=SignalReportCheck.Status.PENDING)
        .select_related("report__team")
    )
    armed = 0
    for check in pending:
        next_run_at = resolved_at + timedelta(minutes=check.soak_minutes or 0)
        if check.kind == SignalReportCheck.Kind.METRIC_THRESHOLD:
            try:
                config = parse_check_config(check.kind, check.config)
                assert isinstance(config, MetricThresholdConfig)
                query = resolve_check_query(config, check.report)
                next_run_at = max(next_run_at, metric_check_ready_at(query, check.report.team, resolved_at))
            except (CheckConfigValidationError, ValueError):
                # An invalid legacy config must not prevent the report's other checks from arming.
                pass
        expires_at = check_schedule_expires_at(
            next_run_at=next_run_at,
            run_interval_minutes=check.run_interval_minutes,
            runs_remaining=check.runs_remaining,
            start_at=resolved_at,
        )
        armed += (
            SignalReportCheck.objects.for_team(team_id)
            .filter(id=check.id, status=SignalReportCheck.Status.PENDING)
            .update(
                status=SignalReportCheck.Status.ACTIVE,
                next_run_at=next_run_at,
                measurement_start_at=resolved_at if check.kind == SignalReportCheck.Kind.METRIC_THRESHOLD else None,
                expires_at=expires_at,
                updated_at=resolved_at,
            )
        )
    return armed
