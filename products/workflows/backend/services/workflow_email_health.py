from dataclasses import replace
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from prometheus_client import Counter

from posthog.api.app_metrics2 import fetch_app_metric_totals_by_source, fetch_app_metric_totals_by_team_and_source
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers
from posthog.schema_enums import ProductKey
from posthog.tasks.email import send_workflow_email_sending_paused, send_workflow_email_sending_warning

from products.workflows.backend.facade.contracts import (
    COMPLAINT_METRIC,
    EMAIL_HEALTH_METRIC_NAMES,
    HARD_BOUNCE_METRIC,
    SENT_METRIC,
    EmailSendingCounts,
    StaffPausedError,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.email_sending_attribution import fold_email_totals_by_flow

logger = structlog.get_logger(__name__)

APP_SOURCE: Final[str] = "hog_flow"

PAUSED_BY_AUTO: Final[str] = "auto"
PAUSED_BY_STAFF: Final[str] = "staff"


def pause_requires_staff(*, paused_at: datetime | None, paused_by: str, resumed_at: datetime | None) -> bool:
    """Whether only staff can clear this pause.

    Staff pauses always. Automatic pauses too when they landed within the repeat window of the
    previous resume: the workflow already got its self-serve second chance and re-tripped, so
    polling the resume endpoint cannot keep a spammy workflow sending indefinitely.
    """
    if paused_at is None:
        return False
    if paused_by == PAUSED_BY_STAFF:
        return True
    if resumed_at is None:
        return False
    window = timedelta(days=settings.WORKFLOW_EMAIL_AUTO_PAUSE_REPEAT_WINDOW_DAYS)
    return paused_at - resumed_at <= window


Signal = Literal["complaint", "bounce"]

workflow_email_auto_pause_total = Counter(
    "workflow_email_auto_pause_total",
    "Workflows whose email the deliverability detector paused, or would have paused while it runs "
    "with enforcement off.",
    labelnames=["signal", "window", "mode", "scope"],
)

workflow_email_warning_total = Counter(
    "workflow_email_warning_total",
    "Workflows whose admins the deliverability detector warned about rates approaching the pause "
    "thresholds, or would have warned while it runs with enforcement off.",
    labelnames=["signal", "window", "mode", "scope"],
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
class JudgedCounts:
    counts: EmailSendingCounts
    earlier_sent: int
    transactional: bool = False


@frozen
class ProjectBreach:
    sent: int
    events: int
    rate: float
    earlier_sent: int = 0


@frozen
class PauseDecision:
    team_id: int
    hog_flow_id: str
    hog_flow_name: str
    threshold: DetectorThreshold
    sent: int
    events: int
    rate: float
    project: ProjectBreach | None = None
    earlier_sent: int = 0
    transactional: bool = False

    @property
    def reason(self) -> str:
        """What the customer is told, in the pause email, the workflow banner and the API."""
        if self.project is None:
            return self._own_reason
        return (
            f"{self._signal_text} across this project's workflows passed the pause limit in "
            f"{self.threshold.window_description}. This workflow sent {self.sent:,} emails in that time, "
            f"and {self.events:,} of the {self._events_text} came from it."
        )

    @property
    def warning_reason(self) -> str:
        if self.project is None:
            return self._own_reason
        return (
            f"{self._signal_text} reached {_format_rate(self.project.rate)} of the {self.project.sent:,} emails "
            f"this project's workflows sent in {self.threshold.window_description}. This workflow sent "
            f"{self.sent:,} of those emails, and {self.events:,} of the {self._events_text} came from it."
        )

    @property
    def _own_reason(self) -> str:
        return (
            f"{self._signal_text} reached {_format_rate(self.rate)} of the {self.sent:,} emails this workflow "
            f"sent in {self.threshold.window_description}."
        )

    @property
    def _signal_text(self) -> str:
        return "Spam complaints" if self.threshold.signal == "complaint" else "Emails to addresses that do not exist"

    @property
    def _events_text(self) -> str:
        return "spam complaints" if self.threshold.signal == "complaint" else "emails to addresses that do not exist"


def sends_only_transactional_email(actions: object) -> bool:
    steps = [
        (str(action.get("type")), config if isinstance(config := action.get("config"), dict) else {})
        for action in (actions if isinstance(actions, list) else [])
        if isinstance(action, dict)
    ]
    email_configs = [config for step_type, config in steps if step_type == "function_email"]
    runs_the_email_template_elsewhere = any(
        step_type.startswith("function")
        and step_type != "function_email"
        and config.get("template_id") == "template-email"
        for step_type, config in steps
    )
    return (
        bool(email_configs)
        and not runs_the_email_template_elsewhere
        and all(config.get("message_category_type") == "transactional" for config in email_configs)
    )


def _transactional_by_flow(*, team_id: int, flow_ids: list[str]) -> dict[str, bool]:
    if not flow_ids:
        return {}
    return {
        str(flow_id): sends_only_transactional_email(actions)
        for flow_id, actions in HogFlow.objects.filter(team_id=team_id, id__in=flow_ids).values_list("id", "actions")
    }


def _shown_percent(rate: float) -> float:
    return float(_format_rate(rate).removesuffix("%"))


def _format_rate(rate: float) -> str:
    percent = rate * 100
    # Complaint thresholds live below 1%, so a whole-number percentage would round a 0.3% breach
    # to "0%". Two decimals keep every threshold in the table readable.
    return f"{percent:.2f}".rstrip("0").rstrip(".") + "%"


def _hour_floor(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _hour_ceil(value: datetime) -> datetime:
    floored = _hour_floor(value)
    return floored if floored == value else floored + timedelta(hours=1)


def _rate(events: int, sent: int) -> float:
    # Sends are counted at send time but feedback when it arrives, so feedback landing just inside
    # the window for sends just outside it can push the ratio past 1. Clamp to 100%, matching the
    # reputation endpoint: past 100% the number stops meaning anything.
    return min(1.0, events / sent) if sent else 0.0


def _crosses(*, events: int, sent: int, earlier_sent: int, rate: float) -> bool:
    return _rate(events, sent) >= rate and _rate(events, max(sent, earlier_sent)) >= rate


def _discover_candidate_team_ids(*, now: datetime, thresholds: list[DetectorThreshold]) -> set[int]:
    """Find the teams worth looking at, with the volume gates pushed into ClickHouse.

    One pass per window across the whole fleet, never a query per team. The gates are applied at
    the team level, so a workflow whose feedback is spread across many batch jobs (none of them
    individually over a gate) still surfaces its team. Batch sends are the detector's main case,
    so per-source gating would let exactly that shape escape. Over-selection is fine: the second
    pass computes exact per-workflow totals before any decision.
    """
    candidate_team_ids: set[int] = set()
    before = _hour_floor(now)
    for window, group in _thresholds_by_window(thresholds).items():
        totals = fetch_app_metric_totals_by_team_and_source(
            app_source=APP_SOURCE,
            name=EMAIL_HEALTH_METRIC_NAMES,
            after=before - window,
            before=before,
            hour_aligned=True,
            per_source=False,
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
    *, team_ids: list[int], after: datetime, before: datetime
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
        before=before,
        hour_aligned=True,
        team_ids=team_ids,
    )
    folded: dict[int, tuple[dict[str, EmailSendingCounts], dict[str, str]]] = {}
    for team_id, totals_by_source in totals_by_team.items():
        result = fold_email_totals_by_flow(
            team_id=team_id, totals_by_source=totals_by_source, flows=HogFlow.objects.filter(team_id=team_id)
        )
        folded[team_id] = (result.counts_by_flow, result.names_by_flow_id)
    return folded


def _clamped_counts_for_flow(*, flow: HogFlow, after: datetime, before: datetime) -> EmailSendingCounts:
    """Totals for one workflow over a window that starts after its last resume."""
    if after >= before:
        # No complete hour has passed since the resume, so there is nothing judgeable yet.
        return EmailSendingCounts()
    totals_by_source = fetch_app_metric_totals_by_source(
        team_id=flow.team_id,
        app_source=APP_SOURCE,
        after=after,
        before=before,
        hour_aligned=True,
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
    earlier_sent: int,
    threshold: DetectorThreshold,
    transactional: bool,
) -> PauseDecision | None:
    events = _events_for_signal(counts, threshold.signal)
    # Both volume gates first: 1 complaint out of 12 sends is a 8% rate and no information.
    if counts.sent < threshold.min_sent or events < threshold.min_events:
        return None
    if not _crosses(events=events, sent=counts.sent, earlier_sent=earlier_sent, rate=threshold.rate):
        return None
    return PauseDecision(
        team_id=flow.team_id,
        hog_flow_id=str(flow.id),
        hog_flow_name=flow_name,
        threshold=threshold,
        sent=counts.sent,
        events=events,
        rate=_rate(events, counts.sent),
        earlier_sent=earlier_sent,
        transactional=transactional,
    )


def _project_breach(
    *,
    flow: HogFlow,
    flow_name: str,
    counts: EmailSendingCounts,
    earlier_sent: int,
    project_counts: EmailSendingCounts,
    project_earlier_sent: int,
    threshold: DetectorThreshold,
) -> PauseDecision | None:
    project_events = _events_for_signal(project_counts, threshold.signal)
    if project_counts.sent < threshold.min_sent or project_events < threshold.min_events:
        return None
    if not _crosses(
        events=project_events, sent=project_counts.sent, earlier_sent=project_earlier_sent, rate=threshold.rate
    ):
        return None
    events = _events_for_signal(counts, threshold.signal)
    if events == 0 or not _crosses(events=events, sent=counts.sent, earlier_sent=earlier_sent, rate=threshold.rate):
        return None
    return PauseDecision(
        team_id=flow.team_id,
        hog_flow_id=str(flow.id),
        hog_flow_name=flow_name,
        threshold=threshold,
        sent=counts.sent,
        events=events,
        rate=_rate(events, counts.sent),
        project=ProjectBreach(
            sent=project_counts.sent,
            events=project_events,
            rate=_rate(project_events, project_counts.sent),
            earlier_sent=project_earlier_sent,
        ),
        earlier_sent=earlier_sent,
    )


def _first_breach(
    *,
    flow: HogFlow,
    flow_name: str,
    judged: JudgedCounts,
    project: JudgedCounts | None,
    thresholds: list[DetectorThreshold],
    below_pause_rate: bool = False,
) -> PauseDecision | None:
    for threshold in thresholds:
        decision = _breach(
            flow=flow,
            flow_name=flow_name,
            counts=judged.counts,
            earlier_sent=judged.earlier_sent,
            threshold=threshold,
            transactional=judged.transactional,
        )
        if decision is not None and (not below_pause_rate or _below_pause_rate(decision)):
            return decision
    if project is None:
        return None
    for threshold in (threshold for threshold in thresholds if threshold.signal == "bounce"):
        decision = _project_breach(
            flow=flow,
            flow_name=flow_name,
            counts=judged.counts,
            earlier_sent=judged.earlier_sent,
            project_counts=project.counts,
            project_earlier_sent=project.earlier_sent,
            threshold=threshold,
        )
        if decision is not None and (not below_pause_rate or _below_pause_rate(decision)):
            return decision
    return None


def _below_pause_rate(warning: PauseDecision) -> bool:
    shown_rate = warning.project.rate if warning.project is not None else warning.rate
    return _shown_percent(shown_rate) < _shown_percent(_pause_rate_for(warning.threshold))


def _judged_alone(flow_id: str, judged: JudgedCounts) -> bool:
    return flow_id in settings.WORKFLOW_EMAIL_AUTO_PAUSE_EXEMPT_WORKFLOW_IDS or judged.transactional


def _project_counts(judged: dict[str, tuple[HogFlow, JudgedCounts]]) -> JudgedCounts:
    counted = [counts for flow_id, (_, counts) in judged.items() if not _judged_alone(flow_id, counts)]
    return JudgedCounts(
        counts=EmailSendingCounts(
            sent=sum(item.counts.sent for item in counted),
            bounced_hard=sum(item.counts.bounced_hard for item in counted),
            complained=sum(item.counts.complained for item in counted),
        ),
        earlier_sent=sum(
            max(item.counts.sent, item.earlier_sent) if item.counts.bounced_hard else item.counts.sent
            for item in counted
        ),
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
    transactional_by_flow: dict[str, bool] = {}
    # Whole hours only: the metrics table collapses rows per clock hour with an arbitrary surviving
    # raw timestamp, so a mid-hour bound would include or exclude a whole collapsed hour by merge
    # luck, and the two sides of a rate could disagree about the edge hour. The current partial
    # hour is excluded, which adds up to an hour of detection lag on top of the hourly cadence.
    window_end = _hour_floor(now)
    for window, group in sorted(_thresholds_by_window(thresholds).items()):
        window_start = window_end - window
        warn_group = [threshold for threshold in warn_thresholds if threshold.window == window]
        counts_by_team = _counts_by_flow(team_ids=sorted(candidate_team_ids), after=window_start, before=window_end)
        earlier_by_team = (
            _counts_by_flow(team_ids=sorted(counts_by_team), after=window_start - window, before=window_start)
            if counts_by_team
            else {}
        )
        for team_id, (counts_by_flow, names_by_flow_id) in counts_by_team.items():
            earlier_by_flow = earlier_by_team.get(team_id, ({}, {}))[0]
            transactional_by_flow.update(
                _transactional_by_flow(
                    team_id=team_id,
                    flow_ids=[
                        flow_id
                        for flow_id in counts_by_flow
                        if flow_id in flows_by_id and flow_id not in transactional_by_flow
                    ],
                )
            )
            judged: dict[str, tuple[HogFlow, JudgedCounts]] = {}
            for flow_id, counts in counts_by_flow.items():
                flow = flows_by_id.get(flow_id)
                if flow is None or flow.team_id != team_id:
                    continue
                effective_counts = counts
                earlier_sent = earlier_by_flow.get(flow_id, EmailSendingCounts()).sent
                resumed_at = flow.email_sending_resumed_at
                if resumed_at is not None and _hour_ceil(resumed_at) > window_start:
                    # Re-arm after a resume. Without this, feedback that arrived before the pause
                    # is still inside the window, so resuming would immediately re-trip on it.
                    # The clamp starts at the first full hour after the resume: the resume hour's
                    # rows can hold pre-resume feedback merged with post-resume feedback, so that
                    # partial hour is not judgeable either way.
                    clamped_start = _hour_ceil(resumed_at)
                    effective_counts = _clamped_counts_for_flow(flow=flow, after=clamped_start, before=window_end)
                    earlier_sent = _clamped_counts_for_flow(
                        flow=flow, after=clamped_start - (window_end - clamped_start), before=clamped_start
                    ).sent
                judged[flow_id] = (
                    flow,
                    JudgedCounts(
                        counts=effective_counts,
                        earlier_sent=earlier_sent,
                        transactional=transactional_by_flow.get(flow_id, False),
                    ),
                )
            # Workflows paused by an earlier sweep are out of scope, so the feedback that paused one
            # cannot pause its siblings again.
            project = _project_counts(judged)
            for flow_id, (flow, flow_counts) in judged.items():
                # One pause per workflow per sweep. The first breach is the one reported, and the
                # windows are walked shortest first so the reason names the tightest signal.
                if flow_id in paused_flow_ids:
                    continue
                flow_name = names_by_flow_id.get(flow_id, "")
                decision = _first_breach(
                    flow=flow,
                    flow_name=flow_name,
                    judged=flow_counts,
                    project=None if _judged_alone(flow_id, flow_counts) else project,
                    thresholds=group,
                )
                if decision is not None:
                    pauses.append(decision)
                    paused_flow_ids.add(flow_id)
                    continue
                if flow_id in warnings_by_flow:
                    continue
                warned_at = flow.email_sending_warned_at
                if warned_at is not None and warned_at > warn_cutoff:
                    continue
                warning = _first_breach(
                    flow=flow,
                    flow_name=flow_name,
                    judged=flow_counts,
                    project=None if _judged_alone(flow_id, flow_counts) else project,
                    thresholds=warn_group,
                    below_pause_rate=True,
                )
                if warning is not None:
                    warnings_by_flow[flow_id] = warning
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
            .only("id", "team_id", "email_sending_paused_at", "email_sending_resumed_at")
            .first()
        )
        if flow is None or flow.email_sending_paused_at is not None:
            return False
        # A pause landing inside the repeat window of the previous resume is staff-resumable only,
        # and its email must not point the customer at a resume button that will refuse them.
        staff_only = pause_requires_staff(paused_at=now, paused_by=paused_by, resumed_at=flow.email_sending_resumed_at)
        HogFlow.objects.filter(id=hog_flow_id, team_id=team_id).update(
            email_sending_paused_at=now,
            email_sending_paused_reason=reason,
            email_sending_paused_by=paused_by,
        )
        # Robust: a failing reload publish must not stop the callbacks after it. Without this, the
        # pause commits but the admin email is never queued, and later runs skip the already-paused
        # workflow, so the notification is never retried. Workers still catch up on cache expiry.
        transaction.on_commit(
            lambda: reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[hog_flow_id]), robust=True
        )
        # Dispatch after commit so a rollback can't leave an email claiming a pause that was never
        # persisted.
        transaction.on_commit(
            lambda: send_workflow_email_sending_paused.delay(
                team_id=team_id,
                hog_flow_id=hog_flow_id,
                hog_flow_name=hog_flow_name,
                reason=reason,
                paused_at=now.isoformat(),
                resumable=not staff_only,
                staff_pause=paused_by == PAUSED_BY_STAFF,
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
                reason=decision.warning_reason,
                pause_rate=_format_rate(pause_rate),
                warned_at=now.isoformat(),
                **({"transactional": True} if decision.transactional else {}),
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
        if not enabled or _exempt(decision):
            workflow_email_auto_pause_total.labels(
                signal=decision.threshold.signal,
                window=decision.threshold.window_label,
                mode=_unenforced_mode(enabled),
                scope=_scope(decision),
            ).inc()
            logger.info(
                "would_pause_workflow_email_sending", mode=_unenforced_mode(enabled), **_decision_log_fields(decision)
            )
            continue
        if decision.transactional:
            workflow_email_auto_pause_total.labels(
                signal=decision.threshold.signal,
                window=decision.threshold.window_label,
                mode="transactional",
                scope=_scope(decision),
            ).inc()
            logger.warning("would_pause_workflow_email_sending", mode="transactional", **_decision_log_fields(decision))
            failed += _warn(decision, now=now)
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
            signal=decision.threshold.signal,
            window=decision.threshold.window_label,
            mode="applied",
            scope=_scope(decision),
        ).inc()
        logger.warning("paused_workflow_email_sending", **_decision_log_fields(decision))
    for decision in decisions.warnings:
        if not enabled or _exempt(decision):
            workflow_email_warning_total.labels(
                signal=decision.threshold.signal,
                window=decision.threshold.window_label,
                mode=_unenforced_mode(enabled),
                scope=_scope(decision),
            ).inc()
            logger.info(
                "would_warn_workflow_email_sending", mode=_unenforced_mode(enabled), **_decision_log_fields(decision)
            )
            continue
        failed += _warn(decision, now=now)
    if failed:
        logger.warning("workflow_email_health_sweep_partial_failure", failed=failed)
    return applied


def _warn(decision: PauseDecision, *, now: datetime) -> int:
    try:
        warned = apply_warning(decision, now=now)
    except Exception:
        logger.exception("warn_workflow_email_sending_failed", **_decision_log_fields(decision))
        return 1
    if warned:
        workflow_email_warning_total.labels(
            signal=decision.threshold.signal,
            window=decision.threshold.window_label,
            mode="applied",
            scope=_scope(decision),
        ).inc()
        logger.warning("warned_workflow_email_sending", **_decision_log_fields(decision))
    return 0


def _exempt(decision: PauseDecision) -> bool:
    return decision.hog_flow_id in settings.WORKFLOW_EMAIL_AUTO_PAUSE_EXEMPT_WORKFLOW_IDS


def _unenforced_mode(enabled: bool) -> str:
    return "exempt" if enabled else "dry_run"


def _scope(decision: PauseDecision) -> str:
    return "workflow" if decision.project is None else "project"


def _decision_log_fields(decision: PauseDecision) -> dict[str, str | int | float]:
    fields: dict[str, str | int | float] = {
        "team_id": decision.team_id,
        "hog_flow_id": decision.hog_flow_id,
        "hog_flow_name": decision.hog_flow_name,
        "signal": decision.threshold.signal,
        "window": decision.threshold.window_label,
        "emails_sent": decision.sent,
        "earlier_emails_sent": decision.earlier_sent,
        "events": decision.events,
        "rate": decision.rate,
        "threshold_rate": decision.threshold.rate,
        "scope": _scope(decision),
        "transactional": decision.transactional,
    }
    if decision.project is not None:
        fields["project_emails_sent"] = decision.project.sent
        fields["project_compared_emails_sent"] = decision.project.earlier_sent
        fields["project_rate"] = decision.project.rate
    return fields


def resume_email_sending(
    *, team_id: int, hog_flow_id: UUID, actor: str = "customer", now: datetime | None = None
) -> datetime | None:
    """Clear a workflow's pause. Returns the resume time, or None when it was not paused.

    A staff pause exists because the automatic thresholds could not see the problem, so a customer
    must not be able to clear it: only `actor="staff"` may. Raises StaffPausedError so the API can
    tell the customer to contact support instead of reporting "not paused". The row is locked and
    re-read inside the transaction: the caller's instance can be stale, and a customer resume that
    checked an automatic pause must not clear a staff pause that landed in between.

    `email_sending_resumed_at` is what re-arms the detector: every window is clamped to start at
    the first full hour after it, so a workflow that is still misbehaving trips again within a
    couple of hours on fresh feedback instead of on the feedback that caused the first pause.
    """
    now = now or timezone.now()
    with transaction.atomic():
        locked = (
            HogFlow.objects.select_for_update()
            .filter(id=hog_flow_id, team_id=team_id)
            .only("id", "team_id", "email_sending_paused_at", "email_sending_paused_by", "email_sending_resumed_at")
            .first()
        )
        if locked is None or locked.email_sending_paused_at is None:
            return None
        if actor != PAUSED_BY_STAFF and pause_requires_staff(
            paused_at=locked.email_sending_paused_at,
            paused_by=locked.email_sending_paused_by,
            resumed_at=locked.email_sending_resumed_at,
        ):
            raise StaffPausedError("Only PostHog staff can resume this pause.")
        HogFlow.objects.filter(id=hog_flow_id, team_id=team_id).update(
            email_sending_paused_at=None,
            email_sending_paused_reason="",
            email_sending_paused_by="",
            email_sending_resumed_at=now,
        )
        transaction.on_commit(
            lambda: reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[str(hog_flow_id)]), robust=True
        )
    return now


def resume_workflow_email_sending(flow: HogFlow, *, actor: str = "customer", now: datetime | None = None) -> bool:
    """Clear a workflow's pause and mirror the write onto `flow`. Returns False when it was not paused."""
    resumed_at = resume_email_sending(team_id=flow.team_id, hog_flow_id=flow.id, actor=actor, now=now)
    if resumed_at is None:
        return False
    # The caller serializes these back to the customer, so mirror what was written.
    flow.email_sending_paused_at = None
    flow.email_sending_paused_reason = ""
    flow.email_sending_paused_by = ""
    flow.email_sending_resumed_at = resumed_at
    return True
