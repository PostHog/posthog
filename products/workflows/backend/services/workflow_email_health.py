from dataclasses import replace
from datetime import datetime, timedelta
from typing import Final, Literal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from prometheus_client import Counter

from posthog.api.app_metrics2 import fetch_app_metric_totals_by_source, fetch_app_metric_totals_by_team_and_source
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.schema_enums import ProductKey
from posthog.tasks.email import send_workflow_email_sending_paused, send_workflow_email_sending_warning

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.email_sending_attribution import (
    COMPLAINT_METRIC,
    EMAIL_HEALTH_METRIC_NAMES,
    HARD_BOUNCE_METRIC,
    SENT_METRIC,
    EmailSendingCounts,
    fold_email_totals_by_flow,
)

logger = structlog.get_logger(__name__)

APP_SOURCE: Final[str] = "hog_flow"

PAUSED_BY_AUTO: Final[str] = "auto"
PAUSED_BY_STAFF: Final[str] = "staff"


class StaffPausedError(Exception):
    """A customer tried to resume a pause staff placed. Only staff may clear it."""


Signal = Literal["complaint", "bounce"]

workflow_email_auto_pause_total = Counter(
    "workflow_email_auto_pause_total",
    "Workflows whose email the deliverability detector paused, or would have paused while it runs "
    "with enforcement off.",
    labelnames=["signal", "window", "mode"],
)

workflow_email_warning_total = Counter(
    "workflow_email_warning_total",
    "Workflows whose admins the deliverability detector warned about rates approaching the pause "
    "thresholds, or would have warned while it runs with enforcement off.",
    labelnames=["signal", "window", "mode"],
)


@frozen
class DetectorThreshold:
    """One breach rule. Either signal firing over either window is enough to pause a workflow."""

    signal: Signal
    metric_name: str
    window: timedelta
    # Used in the log record, the metric label and the customer-facing reason.
    window_label: str
    window_description: str
    min_sent: int
    min_events: int
    rate: float


def build_thresholds() -> list[DetectorThreshold]:
    """The live threshold table, read from settings on every sweep so a region can retune it
    without a deploy."""
    return [
        DetectorThreshold(
            signal="complaint",
            metric_name=COMPLAINT_METRIC,
            window=timedelta(hours=1),
            window_label="1h",
            window_description="the last hour",
            min_sent=settings.WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_1H,
            min_events=settings.WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_MIN_EVENTS_1H,
            rate=settings.WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_1H,
        ),
        DetectorThreshold(
            signal="complaint",
            metric_name=COMPLAINT_METRIC,
            window=timedelta(hours=24),
            window_label="24h",
            window_description="the last 24 hours",
            min_sent=settings.WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_24H,
            min_events=settings.WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_MIN_EVENTS_24H,
            rate=settings.WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_24H,
        ),
        DetectorThreshold(
            signal="bounce",
            metric_name=HARD_BOUNCE_METRIC,
            window=timedelta(hours=1),
            window_label="1h",
            window_description="the last hour",
            min_sent=settings.WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_1H,
            min_events=settings.WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_MIN_EVENTS_1H,
            rate=settings.WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_RATE_1H,
        ),
        DetectorThreshold(
            signal="bounce",
            metric_name=HARD_BOUNCE_METRIC,
            window=timedelta(hours=24),
            window_label="24h",
            window_description="the last 24 hours",
            min_sent=settings.WORKFLOW_EMAIL_AUTO_PAUSE_MIN_SENT_24H,
            min_events=settings.WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_MIN_EVENTS_24H,
            rate=settings.WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_RATE_24H,
        ),
    ]


def build_warn_thresholds() -> list[DetectorThreshold]:
    """The warning band's lower edge: the pause table with lower rates and the same volume gates.
    A workflow between a warn rate and its pause rate gets a heads-up email instead of a pause."""
    warn_rates = {
        ("complaint", "1h"): settings.WORKFLOW_EMAIL_WARN_COMPLAINT_RATE_1H,
        ("complaint", "24h"): settings.WORKFLOW_EMAIL_WARN_COMPLAINT_RATE_24H,
        ("bounce", "1h"): settings.WORKFLOW_EMAIL_WARN_BOUNCE_RATE_1H,
        ("bounce", "24h"): settings.WORKFLOW_EMAIL_WARN_BOUNCE_RATE_24H,
    }
    return [
        replace(threshold, rate=warn_rates[(threshold.signal, threshold.window_label)])
        for threshold in build_thresholds()
    ]


@frozen
class PauseDecision:
    team_id: int
    hog_flow_id: str
    hog_flow_name: str
    threshold: DetectorThreshold
    sent: int
    events: int
    rate: float

    @property
    def reason(self) -> str:
        """What the customer is told, in the pause email, the workflow banner and the API."""
        signal_text = (
            "Spam complaints" if self.threshold.signal == "complaint" else "Emails to addresses that do not exist"
        )
        return (
            f"{signal_text} reached {_format_rate(self.rate)} of the {self.sent:,} emails this workflow "
            f"sent in {self.threshold.window_description}."
        )


def _format_rate(rate: float) -> str:
    percent = rate * 100
    # Complaint thresholds live below 1%, so a whole-number percentage would round a 0.3% breach
    # to "0%". Two decimals keep every threshold in the table readable.
    return f"{percent:.2f}".rstrip("0").rstrip(".") + "%"


def _rate(events: int, sent: int) -> float:
    # Sends are counted at send time but feedback when it arrives, so feedback landing just inside
    # the window for sends just outside it can push the ratio past 1. Clamp to 100%, matching the
    # reputation endpoint: past 100% the number stops meaning anything.
    return min(1.0, events / sent) if sent else 0.0


def _discover_candidate_team_ids(*, now: datetime, thresholds: list[DetectorThreshold]) -> set[int]:
    """Find the teams worth looking at, with the volume gates pushed into ClickHouse.

    One sweep per window across the whole fleet, never a query per team. The gates are applied per
    `app_source_id` rather than per workflow, so a workflow whose feedback is spread thinly across
    many batch jobs (none of them individually over a gate) is not discovered. That direction is
    the safe one: it under-detects rather than pausing a workflow that is fine.
    """
    candidate_team_ids: set[int] = set()
    for window, group in _thresholds_by_window(thresholds).items():
        totals = fetch_app_metric_totals_by_team_and_source(
            app_source=APP_SOURCE,
            name=EMAIL_HEALTH_METRIC_NAMES,
            after=now - window,
            min_totals={SENT_METRIC: min(threshold.min_sent for threshold in group)},
            any_min_totals={threshold.metric_name: threshold.min_events for threshold in group},
        )
        candidate_team_ids.update(totals)
    return candidate_team_ids


def _thresholds_by_window(thresholds: list[DetectorThreshold]) -> dict[timedelta, list[DetectorThreshold]]:
    by_window: dict[timedelta, list[DetectorThreshold]] = {}
    for threshold in thresholds:
        by_window.setdefault(threshold.window, []).append(threshold)
    return by_window


def _counts_by_flow(
    *, team_ids: list[int], after: datetime
) -> dict[int, tuple[dict[str, EmailSendingCounts], dict[str, str]]]:
    """Exact per-workflow totals for the candidate teams, with batch-job counts folded in.

    The discovery pass gates per `app_source_id`, so its rows alone would undercount a workflow's
    clean sends and read as a worse rate than the workflow really has. This second pass keeps no
    `HAVING`, so every source row for these teams is counted, which is what makes the rate the
    detector acts on the same number the Reputation tab shows.
    """
    totals_by_team = fetch_app_metric_totals_by_team_and_source(
        app_source=APP_SOURCE,
        name=EMAIL_HEALTH_METRIC_NAMES,
        after=after,
        team_ids=team_ids,
    )
    folded: dict[int, tuple[dict[str, EmailSendingCounts], dict[str, str]]] = {}
    for team_id, totals_by_source in totals_by_team.items():
        result = fold_email_totals_by_flow(
            team_id=team_id, totals_by_source=totals_by_source, flows=HogFlow.objects.filter(team_id=team_id)
        )
        folded[team_id] = (result.counts_by_flow, result.names_by_flow_id)
    return folded


def _clamped_counts_for_flow(*, flow: HogFlow, after: datetime) -> EmailSendingCounts:
    """Totals for one workflow over a window that starts after its last resume."""
    totals_by_source = fetch_app_metric_totals_by_source(
        team_id=flow.team_id,
        app_source=APP_SOURCE,
        after=after,
        name=EMAIL_HEALTH_METRIC_NAMES,
    )
    result = fold_email_totals_by_flow(
        team_id=flow.team_id,
        totals_by_source=totals_by_source,
        flows=HogFlow.objects.filter(id=flow.id),
    )
    return result.counts_by_flow.get(str(flow.id), EmailSendingCounts())


def _events_for_signal(counts: EmailSendingCounts, signal: Signal) -> int:
    return counts.complained if signal == "complaint" else counts.bounced_hard


def _breach(
    *,
    flow: HogFlow,
    flow_name: str,
    counts: EmailSendingCounts,
    threshold: DetectorThreshold,
) -> PauseDecision | None:
    events = _events_for_signal(counts, threshold.signal)
    # Both volume gates first: 1 complaint out of 12 sends is a 8% rate and no information.
    if counts.sent < threshold.min_sent or events < threshold.min_events:
        return None
    rate = _rate(events, counts.sent)
    if rate < threshold.rate:
        return None
    return PauseDecision(
        team_id=flow.team_id,
        hog_flow_id=str(flow.id),
        hog_flow_name=flow_name,
        threshold=threshold,
        sent=counts.sent,
        events=events,
        rate=rate,
    )


@frozen
class DetectorDecisions:
    pauses: list[PauseDecision]
    # Workflows inside the warning band: over a warn rate, under every pause rate, and not warned
    # within the cooldown. A workflow never appears in both lists; the pause wins.
    warnings: list[PauseDecision]


def find_workflow_email_pauses(*, now: datetime | None = None) -> list[PauseDecision]:
    """Decide which workflows have earned an email pause. Reads only; writes nothing."""
    return find_workflow_email_decisions(now=now).pauses


def find_workflow_email_decisions(*, now: datetime | None = None) -> DetectorDecisions:
    """Decide which workflows have earned an email pause, and which are approaching one and get a
    warning instead. Reads only; writes nothing."""
    now = now or timezone.now()
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.ENRICHMENT)
    thresholds = build_thresholds()
    warn_thresholds = build_warn_thresholds()

    candidate_team_ids = _discover_candidate_team_ids(now=now, thresholds=thresholds)
    if not candidate_team_ids:
        return DetectorDecisions(pauses=[], warnings=[])

    # Already-paused workflows are skipped: the pause is in force and a second decision would only
    # re-notify. Resuming is what puts a workflow back in scope.
    flows_by_id = {
        str(flow.id): flow
        for flow in HogFlow.objects.filter(team_id__in=candidate_team_ids, email_sending_paused_at__isnull=True).only(
            "id", "team_id", "name", "email_sending_resumed_at", "email_sending_warned_at"
        )
    }
    if not flows_by_id:
        return DetectorDecisions(pauses=[], warnings=[])

    warn_cutoff = now - timedelta(days=settings.WORKFLOW_EMAIL_WARN_COOLDOWN_DAYS)
    pauses: list[PauseDecision] = []
    warnings_by_flow: dict[str, PauseDecision] = {}
    paused_flow_ids: set[str] = set()
    for window, group in sorted(_thresholds_by_window(thresholds).items()):
        window_start = now - window
        warn_group = [threshold for threshold in warn_thresholds if threshold.window == window]
        counts_by_team = _counts_by_flow(team_ids=sorted(candidate_team_ids), after=window_start)
        for team_id, (counts_by_flow, names_by_flow_id) in counts_by_team.items():
            for flow_id, counts in counts_by_flow.items():
                flow = flows_by_id.get(flow_id)
                # One pause per workflow per sweep. The first breach is the one reported, and the
                # windows are walked shortest first so the reason names the tightest signal.
                if flow is None or flow.team_id != team_id or flow_id in paused_flow_ids:
                    continue
                effective_counts = counts
                resumed_at = flow.email_sending_resumed_at
                if resumed_at is not None and resumed_at > window_start:
                    # Re-arm after a resume. Without this, feedback that arrived before the pause
                    # is still inside the window, so resuming would immediately re-trip on it.
                    effective_counts = _clamped_counts_for_flow(flow=flow, after=resumed_at)
                flow_name = names_by_flow_id.get(flow_id, "")
                for threshold in group:
                    decision = _breach(flow=flow, flow_name=flow_name, counts=effective_counts, threshold=threshold)
                    if decision is not None:
                        pauses.append(decision)
                        paused_flow_ids.add(flow_id)
                        break
                if flow_id in paused_flow_ids or flow_id in warnings_by_flow:
                    continue
                warned_at = flow.email_sending_warned_at
                if warned_at is not None and warned_at > warn_cutoff:
                    continue
                for threshold in warn_group:
                    decision = _breach(flow=flow, flow_name=flow_name, counts=effective_counts, threshold=threshold)
                    if decision is not None:
                        warnings_by_flow[flow_id] = decision
                        break
    # A pause found in a longer window outranks a warning found in a shorter one, so the warning
    # list is settled only after every window ran.
    warnings = [decision for flow_id, decision in warnings_by_flow.items() if flow_id not in paused_flow_ids]
    return DetectorDecisions(pauses=pauses, warnings=warnings)


def pause_workflow_email_sending(
    *,
    team_id: int,
    hog_flow_id: str,
    hog_flow_name: str,
    reason: str,
    paused_by: str = PAUSED_BY_AUTO,
    now: datetime | None = None,
) -> bool:
    """Pause one workflow's email and tell the project's admins.

    Returns False if it was already paused, which is how two overlapping sweeps stay down to one
    notification. The row is locked for the read-compare-write so the loser sees the pause.
    """
    now = now or timezone.now()
    with transaction.atomic():
        flow = (
            HogFlow.objects.select_for_update()
            .filter(id=hog_flow_id, team_id=team_id)
            .only("id", "team_id", "email_sending_paused_at")
            .first()
        )
        if flow is None or flow.email_sending_paused_at is not None:
            return False
        flow.email_sending_paused_at = now
        flow.email_sending_paused_reason = reason
        flow.email_sending_paused_by = paused_by
        # The post_save signal publishes a worker config reload, so in-flight runs and queued batch
        # sends stop at the send choke point rather than only new runs.
        flow.save(update_fields=["email_sending_paused_at", "email_sending_paused_reason", "email_sending_paused_by"])
        # Dispatch after commit so a rollback can't leave an email claiming a pause that was never
        # persisted.
        transaction.on_commit(
            lambda: send_workflow_email_sending_paused.delay(
                team_id=team_id,
                hog_flow_id=hog_flow_id,
                hog_flow_name=hog_flow_name,
                reason=reason,
                paused_at=now.isoformat(),
                resumable=paused_by != PAUSED_BY_STAFF,
            )
        )
    return True


def apply_pause(decision: PauseDecision, *, now: datetime | None = None) -> bool:
    return pause_workflow_email_sending(
        team_id=decision.team_id,
        hog_flow_id=decision.hog_flow_id,
        hog_flow_name=decision.hog_flow_name,
        reason=decision.reason,
        now=now,
    )


def apply_warning(decision: PauseDecision, *, now: datetime | None = None) -> bool:
    """Stamp the warning and email the project's admins. Returns False when another run got there
    first, or the workflow was paused or warned within the cooldown in the meantime.

    A filtered `update` rather than `save`: the compare-and-set keeps two overlapping runs down to
    one email, and skipping the model signal spares the workers a config reload for a field the
    send path never reads.
    """
    now = now or timezone.now()
    warn_cutoff = now - timedelta(days=settings.WORKFLOW_EMAIL_WARN_COOLDOWN_DAYS)
    with transaction.atomic():
        updated = (
            HogFlow.objects.filter(
                id=decision.hog_flow_id, team_id=decision.team_id, email_sending_paused_at__isnull=True
            )
            .filter(Q(email_sending_warned_at__isnull=True) | Q(email_sending_warned_at__lte=warn_cutoff))
            .update(email_sending_warned_at=now)
        )
        if not updated:
            return False
        pause_rate = _pause_rate_for(decision.threshold)
        transaction.on_commit(
            lambda: send_workflow_email_sending_warning.delay(
                team_id=decision.team_id,
                hog_flow_id=decision.hog_flow_id,
                hog_flow_name=decision.hog_flow_name,
                reason=decision.reason,
                pause_rate=_format_rate(pause_rate),
                warned_at=now.isoformat(),
            )
        )
    return True


def _pause_rate_for(warn_threshold: DetectorThreshold) -> float:
    """The pause rate paired with a warn threshold, named in the warning email so the customer
    knows where the line is."""
    for threshold in build_thresholds():
        if threshold.signal == warn_threshold.signal and threshold.window_label == warn_threshold.window_label:
            return threshold.rate
    return warn_threshold.rate


def sweep_workflow_email_health(*, now: datetime | None = None) -> list[PauseDecision]:
    """Find workflows breaching a complaint or hard bounce threshold and pause their email.

    All workflow email shares one SES account, so complaints and hard bounces from any one project
    degrade delivery for every customer. This pauses the offending workflow only, which is the
    enforcement step that sits between doing nothing and suspending a whole project by hand.

    Workflows approaching a threshold get a warning email instead, so their admins can clean up
    the audience before the pause. The same flag covers both: warnings and pauses turn on together.

    While `WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED` is off nothing is written. Each decision is still
    logged and counted, which is how the thresholds get calibrated before anything enforces.
    """
    now = now or timezone.now()
    decisions = find_workflow_email_decisions(now=now)
    enabled = settings.WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED
    applied: list[PauseDecision] = []
    failed = 0
    for decision in decisions.pauses:
        if not enabled:
            workflow_email_auto_pause_total.labels(
                signal=decision.threshold.signal, window=decision.threshold.window_label, mode="dry_run"
            ).inc()
            logger.info("would_pause_workflow_email_sending", **_decision_log_fields(decision))
            continue
        try:
            # One writer's Redis, database or broker error must not drop every later pause and
            # warning in this sweep. Isolate it so the remaining workflows are still processed; the
            # next hourly run retries the ones left at risk.
            paused = apply_pause(decision, now=now)
        except Exception:
            failed += 1
            logger.exception("pause_workflow_email_sending_failed", **_decision_log_fields(decision))
            continue
        if not paused:
            continue
        applied.append(decision)
        workflow_email_auto_pause_total.labels(
            signal=decision.threshold.signal, window=decision.threshold.window_label, mode="applied"
        ).inc()
        logger.warning("paused_workflow_email_sending", **_decision_log_fields(decision))
    for decision in decisions.warnings:
        if not enabled:
            workflow_email_warning_total.labels(
                signal=decision.threshold.signal, window=decision.threshold.window_label, mode="dry_run"
            ).inc()
            logger.info("would_warn_workflow_email_sending", **_decision_log_fields(decision))
            continue
        try:
            warned = apply_warning(decision, now=now)
        except Exception:
            failed += 1
            logger.exception("warn_workflow_email_sending_failed", **_decision_log_fields(decision))
            continue
        if not warned:
            continue
        workflow_email_warning_total.labels(
            signal=decision.threshold.signal, window=decision.threshold.window_label, mode="applied"
        ).inc()
        logger.warning("warned_workflow_email_sending", **_decision_log_fields(decision))
    if failed:
        logger.warning("workflow_email_health_sweep_partial_failure", failed=failed)
    return applied


def _decision_log_fields(decision: PauseDecision) -> dict:
    return {
        "team_id": decision.team_id,
        "hog_flow_id": decision.hog_flow_id,
        "hog_flow_name": decision.hog_flow_name,
        "signal": decision.threshold.signal,
        "window": decision.threshold.window_label,
        "emails_sent": decision.sent,
        "events": decision.events,
        "rate": decision.rate,
        "threshold_rate": decision.threshold.rate,
    }


def resume_workflow_email_sending(flow: HogFlow, *, actor: str = "customer", now: datetime | None = None) -> bool:
    """Clear a workflow's pause. Returns False when it was not paused.

    A staff pause exists because the automatic thresholds could not see the problem, so a customer
    must not be able to clear it: only `actor="staff"` may. Raises StaffPausedError so the API can
    tell the customer to contact support instead of reporting "not paused".

    `email_sending_resumed_at` is what re-arms the detector: every window is clamped to start after
    it, so a workflow that is still misbehaving trips again within minutes on fresh feedback
    instead of on the feedback that caused the first pause.
    """
    if flow.email_sending_paused_at is None:
        return False
    if actor != PAUSED_BY_STAFF and flow.email_sending_paused_by == PAUSED_BY_STAFF:
        raise StaffPausedError("Only PostHog staff can resume this pause.")
    flow.email_sending_paused_at = None
    flow.email_sending_paused_reason = ""
    flow.email_sending_paused_by = ""
    flow.email_sending_resumed_at = now or timezone.now()
    flow.save(
        update_fields=[
            "email_sending_paused_at",
            "email_sending_paused_reason",
            "email_sending_paused_by",
            "email_sending_resumed_at",
        ],
    )
    return True
