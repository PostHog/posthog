"""Staleness sweep: archive reports that stopped moving, and close the pull requests behind them.

Nothing closes a signal report today. A report re-researches for weeks, its draft pull request
stays open, and neither ever ends on its own — so the inbox and the pull request list both only
ever grow. This module is the missing stop: once a day (`tasks.sweep_stale_signal_reports`) it
decides which reports have run out of things that could still change them, and archives those.

**Two clocks, because one does not work.** The obvious rule is inactivity, and it is right for a
report the pipeline drives: signals stop arriving, research runs out of buckets, nothing moves, and
after `STALE_REPORT_AGE` the report is done whether or not anyone said so. It is wrong for a report
a scout keeps rewriting. A scout runs on its own schedule, so its reports never go quiet — the
worst case we measured reads as active every single day and would never be archived by an
inactivity rule at all. Those reports are judged on human silence instead: `last_human_touch_at`,
at `SCOUT_REPORT_HUMAN_SILENCE`, which is longer than the inactivity window because deciding on a
report takes people weeks.

Scout-touched means `content_revision_count > 0` — a scout has rewritten the report at least once,
which is exactly the population whose machine clock never runs down. The two arms partition the
candidates, so no report is judged by both rules.

**What archiving means here.** `transition_to(SUPPRESSED)` plus a `dismissal` artefact carrying
`STALE_DISMISSAL_REASON`, and nothing else. Both are existing choke points, which is the point:
`receivers.close_pr_when_report_dismissed` already closes the open pull request of any suppressed
report, the inbox already hides suppressed reports and already renders a dismissal chip, and
"restore" already puts a report back where it was. The sweep adds a reason code, not a lifecycle.

**Three gates, all closed by default.** Archiving is customer-visible and closes customer pull
requests, so it does not reach the fleet by deploying. `settings.SIGNAL_STALE_REPORT_REAPER_ENABLED`
is the global switch, the `signals-stale-report-reaper` flag stages the rollout per organization,
and `SignalTeamConfig.stale_report_sweep_enabled` is the team's own opt-in — every team that
existed when this shipped was stamped out of it by the accompanying backfill, so nobody wakes up to
a mass archive of a backlog they have been carrying for months.

Detection is not gated. The sweep always finds its candidates and always emits
`signal_report_stale_detected`, whether or not it may act, which is what makes the rollout
readable before it is enforced: the population and the day counts behind it can be checked against
what we expected before a single report is archived.

Never archived: a report whose implementation pull request was merged. The fix shipped, so whatever
the clocks say, the report is not abandoned.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Dismissal
from products.signals.backend.implementation_pr import fetch_implementation_pr_state_for_reports
from products.signals.backend.models import (
    REAPABLE_REPORT_STATUSES,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalTeamConfig,
)

logger = structlog.get_logger(__name__)

STALE_REPORT_REAPER_FEATURE_FLAG = "signals-stale-report-reaper"

# The dismissal reason code the sweep writes. Never selectable in the dismiss dialog; the inbox
# maps it to a label of its own (see `frontend/inbox/utils/dismissalReasons.ts`).
STALE_DISMISSAL_REASON = "stale"

STALE_REPORT_AGE = timedelta(days=settings.SIGNAL_STALE_REPORT_AGE_DAYS)
SCOUT_REPORT_HUMAN_SILENCE = timedelta(days=settings.SIGNAL_SCOUT_REPORT_HUMAN_SILENCE_DAYS)

# Blast-radius cap: reports archived per sweep, per the whole fleet. The first enforcing sweep on
# a team that opts in meets its entire backlog at once, and archiving is visible in the inbox and
# on GitHub, so it drains over days rather than landing in one pass. Applied in iteration order,
# most stale first, so the sweep works through the backlog instead of re-sampling it.
MAX_ARCHIVES_PER_SWEEP = 200

# How many candidates one sweep examines. Bounds both the pull request lookups and the analytics
# volume on the first run, when the whole standing backlog qualifies at once. Deferrals are
# counted and logged: a capped sweep must read as "more to do", never as a clean bill of health.
MAX_CANDIDATES_PER_SWEEP = 2000

# Merged-pull-request lookups go through the tasks facade, which batches per call.
_PR_LOOKUP_BATCH = 200


@frozen
class StaleCandidate:
    """One report the sweep found, and the evidence it was found on."""

    report: SignalReport
    # Which rule selected it: `inactivity` for a pipeline report, `human_silence` for one a scout
    # has rewritten. Rides the analytics events so the two populations stay separable.
    clock: str
    # Both day counts, on every candidate rather than only the one its own clock used — that is
    # what lets the two thresholds be retuned against each other later.
    days_idle: int
    days_since_human_touch: int
    has_open_pr: bool


@dataclass(frozen=False)
class StaleSweepOutcome:
    """What one sweep did, for logging and analytics."""

    considered: int = 0
    detected: list[StaleCandidate] = field(default_factory=list)
    archived: list[StaleCandidate] = field(default_factory=list)
    # Candidates the sweep could have archived but did not, because the per-sweep cap was already
    # spent. They stay put and are re-derived by the next sweep.
    deferred: int = 0
    # Candidates whose team has not cleared all three gates. Counted so the read-back can tell
    # "nothing was stale" from "plenty was stale and the rollout has not reached it".
    gated: int = 0
    # True when the scan hit `MAX_CANDIDATES_PER_SWEEP`, so the numbers above describe a slice of
    # the backlog rather than all of it.
    scan_truncated: bool = False


def sweep_stale_reports(now: datetime | None = None) -> StaleSweepOutcome:
    """Find every report whose clock ran out, and archive the ones the gates allow.

    Idempotent: an archived report leaves the reapable statuses, so a re-run the same day
    re-derives a strictly smaller candidate set. Detection runs whether or not archiving is
    enabled — see the module docstring.
    """
    now = now or timezone.now()
    outcome = StaleSweepOutcome()
    archiving_allowed = _TeamGates()

    for candidates in _candidate_batches(now, outcome):
        outcome.considered += len(candidates)
        pr_state = fetch_implementation_pr_state_for_reports([str(report.id) for report, _ in candidates])
        for report, clock in candidates:
            pr = pr_state.get(str(report.id))
            if pr is not None and pr.merged:
                # The fix shipped. Whatever the clocks say, this report is not abandoned, and the
                # webhook that resolves it on merge may simply not have landed.
                continue
            candidate = StaleCandidate(
                report=report,
                clock=clock,
                days_idle=_days_since(report.last_activity_at or report.created_at, now),
                days_since_human_touch=_days_since(report.last_human_touch_at or report.created_at, now),
                has_open_pr=pr is not None,
            )
            outcome.detected.append(candidate)
            if not archiving_allowed.for_team(report.team_id):
                outcome.gated += 1
                continue
            if len(outcome.archived) >= MAX_ARCHIVES_PER_SWEEP:
                outcome.deferred += 1
                continue
            if _archive(candidate):
                outcome.archived.append(candidate)

    return outcome


def _candidate_batches(now: datetime, outcome: StaleSweepOutcome) -> Iterator[list[tuple[SignalReport, str]]]:
    """Yield pages of (report, clock) for both arms, most stale first, up to the scan cap.

    Paged rather than materialized: a first sweep meets the whole standing backlog at once, and
    each page costs a pull request lookup, so the page size is what bounds that lookup rather than
    the size of the backlog.
    """
    remaining = MAX_CANDIDATES_PER_SWEEP
    for clock, queryset in (
        ("inactivity", _inactive_reports(now)),
        ("human_silence", _humanly_silent_reports(now)),
    ):
        if remaining <= 0:
            # Checked rather than assumed: spending the cap is not the same as leaving work
            # behind, and the flag is read as "there is more to do".
            outcome.scan_truncated = outcome.scan_truncated or queryset.exists()
            return
        # One more than the cap allows, so hitting it is distinguishable from exhausting the arm.
        found = list(queryset[: remaining + 1])
        if len(found) > remaining:
            outcome.scan_truncated = True
            found = found[:remaining]
        remaining -= len(found)
        for start in range(0, len(found), _PR_LOOKUP_BATCH):
            yield [(report, clock) for report in found[start : start + _PR_LOOKUP_BATCH]]


def _reapable() -> QuerySet[SignalReport]:
    """Fleet-wide: this sweep is genuinely cross-team, and each row carries the team it belongs to."""
    return SignalReport.objects.filter(status__in=REAPABLE_REPORT_STATUSES)


def _older_than(field_name: str, cutoff: datetime) -> Q:
    """Reports whose `field_name` clock ran out, treating a null clock as the report's birth.

    A null only survives the backfill on a report created after it ran and never stamped, which for
    the human clock is the common case: most reports nobody has ever opened.
    """
    return Q(**{f"{field_name}__lt": cutoff}) | Q(**{f"{field_name}__isnull": True, "created_at__lt": cutoff})


def _inactive_reports(now: datetime) -> QuerySet[SignalReport]:
    """Pipeline reports nothing has happened to. Most stale first, so the cap drains the backlog."""
    return (
        _reapable()
        .filter(content_revision_count=0)
        .filter(_older_than("last_activity_at", now - STALE_REPORT_AGE))
        .order_by("last_activity_at", "id")
    )


def _humanly_silent_reports(now: datetime) -> QuerySet[SignalReport]:
    """Scout-rewritten reports no person has touched. Their machine clock never runs down."""
    return (
        _reapable()
        .filter(content_revision_count__gt=0)
        .filter(_older_than("last_human_touch_at", now - SCOUT_REPORT_HUMAN_SILENCE))
        .order_by("last_human_touch_at", "id")
    )


def _days_since(stamp: datetime, now: datetime) -> int:
    return max(0, (now - stamp).days)


class _TeamGates:
    """The three archiving gates, resolved once per team and remembered for the sweep.

    A sweep sees a team's reports in bursts, and the flag check is a network call, so caching is
    what keeps a fleet-wide pass from re-evaluating the same organization hundreds of times.
    """

    def __init__(self) -> None:
        self._by_team: dict[int, bool] = {}

    def for_team(self, team_id: int) -> bool:
        cached = self._by_team.get(team_id)
        if cached is None:
            cached = self._resolve(team_id)
            self._by_team[team_id] = cached
        return cached

    def _resolve(self, team_id: int) -> bool:
        if not settings.SIGNAL_STALE_REPORT_REAPER_ENABLED:
            return False
        config = SignalTeamConfig.objects.filter(team_id=team_id).values_list("stale_report_sweep_enabled", flat=True)
        # Null reads as enabled: a team created after this shipped is opted in, and only the
        # backfill's explicit False (or a team turning it off) opts one out.
        if config.first() is False:
            return False
        organization_id = Team.objects.filter(pk=team_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return False
        return _reaper_flag_enabled(str(organization_id))


def _reaper_flag_enabled(organization_id: str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                STALE_REPORT_REAPER_FEATURE_FLAG,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        # A flag lookup that fails must not archive anything — every gate here is fail-closed.
        logger.warning("signals stale report sweep: flag lookup failed", organization_id=organization_id)
        return False


def _archive(candidate: StaleCandidate) -> bool:
    """Suppress the report and record why. Returns whether it was archived.

    The suppression and its dismissal artefact go in one transaction so the inbox can never show a
    report archived for no stated reason. Closing the pull request is deliberately outside it: the
    `close_pr_when_report_dismissed` receiver schedules that on commit, which is what keeps a
    rolled-back archive from closing a pull request that should still be open.
    """
    report = candidate.report
    # Read by `receivers._pr_close_reason`, so the comment left on the closed pull request says
    # the report went quiet rather than that somebody dismissed it.
    report._pr_close_reason_hint = STALE_DISMISSAL_REASON  # type: ignore[attr-defined]
    try:
        with transaction.atomic():
            updated_fields = report.transition_to(SignalReport.Status.SUPPRESSED)
            report.save(update_fields=updated_fields)
            SignalReportArtefact.append_dismissal(
                team_id=report.team_id,
                report_id=str(report.id),
                content=Dismissal(reason=STALE_DISMISSAL_REASON, note=_archive_note(candidate)),
                attribution=ArtefactAttribution.system(),
            )
    except InvalidStatusTransition:
        # The report moved between the scan and here. The next sweep re-derives it if it is still
        # stale, so losing this one costs nothing.
        logger.info(
            "signals stale report sweep: transition refused",
            report_id=str(report.id),
            team_id=report.team_id,
            status=report.status,
        )
        return False
    except Exception:
        logger.exception("signals stale report sweep: archive failed", report_id=str(report.id))
        return False
    logger.info(
        "signals stale report sweep: archived",
        report_id=str(report.id),
        team_id=report.team_id,
        clock=candidate.clock,
        days_idle=candidate.days_idle,
        days_since_human_touch=candidate.days_since_human_touch,
    )
    return True


def _archive_note(candidate: StaleCandidate) -> str:
    """The line a person reads on the archived report, saying which clock ran out and how long ago."""
    if candidate.clock == "human_silence":
        return (
            f"Archived automatically. A scout kept revising this report, but nobody has looked at it "
            f"in {candidate.days_since_human_touch} days. Restore it if it still matters."
        )
    return (
        f"Archived automatically. Nothing has happened on this report in {candidate.days_idle} days. "
        "Restore it if it still matters."
    )
