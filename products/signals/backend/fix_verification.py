"""Post-merge fix verification: the outcome half of the signals autonomy loop.

Resolution says "a fix PR merged"; this module owns whether the fix actually held.
`schedule_fix_verification` records the pending claim when the tasks GitHub webhook
resolves a report; the verification sweep (temporal) settles it after the soak window.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import structlog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    NoteArtefact,
    RelatedTo,
    parse_artefact_content,
)
from products.signals.backend.models import SignalFixVerification, SignalReport, SignalReportArtefact, SignalScratchpad

logger = structlog.get_logger(__name__)

# How long a resolved report must stay quiet after its fix PR merges before the fix
# counts as verified. Recurrences flip the row to REGRESSED as soon as the sweep sees
# them; only the VERIFIED outcome waits for this deadline.
FIX_VERIFICATION_SOAK_WINDOW = timedelta(days=7)

# Per-sweep cap so a backlog (first deploy, sweep outage) settles over a few ticks
# instead of one unbounded pass.
FIX_VERIFICATION_SWEEP_LIMIT = 500

# Scout scratchpad key prefix for fix outcomes — the memory surface scout runs search at
# prompt-assembly time, so outcomes here are what makes the fleet learn from its fixes.
FIX_OUTCOME_MEMORY_KEY_PREFIX = "fix-outcome:"

# Cap on retained fix-outcome entries per team; oldest are pruned so outcomes can't
# crowd out the scout's other memory.
MAX_FIX_OUTCOME_MEMORY_ENTRIES = 50


def schedule_fix_verification(report: SignalReport, *, task_id: uuid.UUID | None, pr_url: str) -> SignalFixVerification:
    """Record a pending post-merge verification for a report resolved by a merged PR.

    Idempotent per report (webhooks redeliver): the first delivery's row wins.
    """
    verification, created = SignalFixVerification.objects.for_team(report.team_id).get_or_create(
        report=report,
        defaults={
            "team_id": report.team_id,
            "task_id": task_id,
            "pr_url": pr_url,
            "verify_after": timezone.now() + FIX_VERIFICATION_SOAK_WINDOW,
        },
    )
    if created:
        logger.info(
            "signals_fix_verification_scheduled",
            report_id=str(report.id),
            team_id=report.team_id,
            pr_url=pr_url,
            verify_after=verification.verify_after.isoformat(),
        )
    return verification


@dataclass
class FixVerificationSweepStats:
    checked: int = 0
    verified: int = 0
    regressed: int = 0
    inconclusive: int = 0
    regressed_verification_ids: list[str] = field(default_factory=list)


def evaluate_pending_fix_verifications(*, now: datetime | None = None) -> FixVerificationSweepStats:
    """Settle pending fix verifications against what actually happened after the merge.

    A verification is examined when its soak deadline has passed, or earlier as soon as a
    recurrence link appears on the resolved report (regressions shouldn't wait out the
    window). Outcomes:

    - REGRESSED: a live recurrence report exists — the grouping pipeline spawned a fresh
      report for the same issue after the fix merged (`related_to` artefact pair).
    - VERIFIED: the deadline passed with no live recurrence. Recurrences the team
      dismissed as noise don't count against the fix.
    - INCONCLUSIVE: the report left RESOLVED through another door (suppressed, refunded,
      deleted) — no outcome can be attributed to the fix.

    Cross-team by design (the sweep runs unscoped); every per-row query stays pinned to
    the verification's own team.
    """
    now = now or timezone.now()
    post_merge_recurrence_link = Exists(
        SignalReportArtefact.objects.filter(
            report_id=OuterRef("report_id"),
            type=SignalReportArtefact.ArtefactType.RELATED_TO,
            created_at__gt=OuterRef("created_at"),
            # Only the grouping pipeline's system-attributed links count as recurrence
            # evidence — `related_to` is also writable through the artefact API, and a
            # user- or task-authored link must not pull a verification forward.
            created_by__isnull=True,
            task__isnull=True,
        )
    )
    due = (
        SignalFixVerification.all_teams.filter(status=SignalFixVerification.Status.PENDING)
        .filter(Q(verify_after__lte=now) | post_merge_recurrence_link)
        .select_related("report")
        .order_by("verify_after")[:FIX_VERIFICATION_SWEEP_LIMIT]
    )

    stats = FixVerificationSweepStats()
    for verification in due:
        try:
            outcome = _settle_verification(verification, now=now)
        except Exception:
            # The sweep is global: one team's bad row (or a transient DB error) must not
            # stop every later team's verifications from settling. The row stays PENDING
            # and is retried on the next tick.
            logger.exception(
                "signals_fix_verification_settle_failed",
                verification_id=str(verification.id),
                report_id=str(verification.report_id),
                team_id=verification.team_id,
            )
            continue
        if outcome is None:
            continue
        stats.checked += 1
        match outcome:
            case SignalFixVerification.Status.VERIFIED:
                stats.verified += 1
            case SignalFixVerification.Status.REGRESSED:
                stats.regressed += 1
                stats.regressed_verification_ids.append(str(verification.id))
            case SignalFixVerification.Status.INCONCLUSIVE:
                stats.inconclusive += 1
    return stats


def _settle_verification(
    verification: SignalFixVerification, *, now: datetime
) -> "SignalFixVerification.Status | None":
    report = verification.report
    if report.status != SignalReport.Status.RESOLVED:
        return _record_outcome(verification, SignalFixVerification.Status.INCONCLUSIVE, now=now)

    recurrence = _earliest_live_recurrence(verification, report)
    if recurrence is not None:
        return _record_outcome(
            verification, SignalFixVerification.Status.REGRESSED, now=now, regressed_report=recurrence
        )
    if verification.verify_after <= now:
        return _record_outcome(verification, SignalFixVerification.Status.VERIFIED, now=now)
    # A recurrence link exists but every linked report was dismissed/deleted — stay
    # pending until the deadline in case a real recurrence still lands.
    return None


def _earliest_live_recurrence(verification: SignalFixVerification, report: SignalReport) -> SignalReport | None:
    """The first still-live report the grouping pipeline linked to `report` after the merge.

    Only system-attributed links are trusted: `related_to` is also writable through the
    artefact API, and a user- or task-authored link must not decide a terminal outcome.
    Stored content is still treated as untrusted — malformed rows are skipped, not raised,
    so one bad artefact can't poison the verification.
    """
    link_artefacts = SignalReportArtefact.objects.filter(
        report_id=report.id,
        type=SignalReportArtefact.ArtefactType.RELATED_TO,
        created_at__gt=verification.created_at,
        created_by__isnull=True,
        task__isnull=True,
    ).order_by("created_at")

    linked_ids: list[uuid.UUID] = []
    for artefact in link_artefacts:
        linked_id = _parse_linked_report_id(artefact)
        if linked_id is not None:
            linked_ids.append(linked_id)
    if not linked_ids:
        return None

    live_by_id = {
        r.id: r
        for r in SignalReport.objects.filter(id__in=linked_ids, team_id=verification.team_id).exclude(
            status__in=[SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED]
        )
    }
    for linked_id in linked_ids:
        if linked_id in live_by_id:
            return live_by_id[linked_id]
    return None


def _parse_linked_report_id(artefact: SignalReportArtefact) -> uuid.UUID | None:
    try:
        content = parse_artefact_content(artefact.type, artefact.content)
    except ArtefactContentValidationError:
        logger.warning(
            "signals_fix_verification_malformed_link_skipped",
            artefact_id=str(artefact.id),
            report_id=str(artefact.report_id),
            team_id=artefact.team_id,
        )
        return None
    if not isinstance(content, RelatedTo):
        return None
    try:
        return uuid.UUID(content.report_id)
    except ValueError:
        logger.warning(
            "signals_fix_verification_invalid_link_target_skipped",
            artefact_id=str(artefact.id),
            report_id=str(artefact.report_id),
            team_id=artefact.team_id,
        )
        return None


def _record_outcome(
    verification: SignalFixVerification,
    status: "SignalFixVerification.Status",
    *,
    now: datetime,
    regressed_report: SignalReport | None = None,
) -> "SignalFixVerification.Status":
    verification.status = status
    verification.checked_at = now
    update_fields = ["status", "checked_at"]
    if regressed_report is not None:
        verification.regressed_report = regressed_report
        update_fields.append("regressed_report")
    verification.save(update_fields=update_fields)
    logger.info(
        "signals_fix_verification_settled",
        verification_id=str(verification.id),
        report_id=str(verification.report_id),
        team_id=verification.team_id,
        outcome=status,
        pr_url=verification.pr_url,
        regressed_report_id=str(regressed_report.id) if regressed_report else None,
    )
    # The settled row is the source of truth; downstream actions (memory, annotations)
    # are best-effort so one bad write can't wedge the sweep.
    try:
        _act_on_outcome(verification, status, regressed_report)
    except Exception:
        logger.exception(
            "signals_fix_verification_outcome_actions_failed",
            verification_id=str(verification.id),
            outcome=status,
        )
    return status


def _act_on_outcome(
    verification: SignalFixVerification,
    status: "SignalFixVerification.Status",
    regressed_report: SignalReport | None,
) -> None:
    """Feed the outcome back into the loop: annotate the recurrence and remember the lesson."""
    if status == SignalFixVerification.Status.INCONCLUSIVE:
        return

    # These strings become durable, system-authored agent memory that future runs read
    # verbatim, so only system-derived facts (IDs, PR URL, dates) may appear in them.
    # Report title/summary are user-editable prose — interpolating them here would be a
    # prompt-injection path into trusted context; agents that need the title can look the
    # report up by ID and treat it as untrusted.
    report = verification.report
    if status == SignalFixVerification.Status.REGRESSED and regressed_report is not None:
        # The next research/fix agent reads this report's artefact log; without the note it
        # has no way to know a fix was already tried and bounced.
        SignalReportArtefact.add_log(
            team_id=verification.team_id,
            report_id=str(regressed_report.id),
            content=NoteArtefact(
                note=(
                    f"Fix regression: this issue was previously resolved by {verification.pr_url} "
                    f"(report {report.id}), but it recurred after the merge. The previous fix "
                    "did not hold, so understand why before attempting a similar fix."
                ),
                author="fix_verification",
            ),
            attribution=ArtefactAttribution.system(),
        )
        memory = (
            f"Fix outcome (regressed): report {report.id} was resolved by {verification.pr_url}, "
            f"but the issue recurred and a new report was opened ({regressed_report.id}). "
            "A similar fix alone is not enough; find out why it did not hold before re-attempting."
        )
    else:
        memory = (
            f"Fix outcome (verified): report {report.id} was resolved by {verification.pr_url} "
            f"and stayed quiet through the {FIX_VERIFICATION_SOAK_WINDOW.days}-day soak window. "
            "This class of fix holds."
        )

    # noqa rationale: `scout_harness.tools` package import chain reaches back into this
    # module via the temporal package — deferring breaks that true circular import.
    from products.signals.backend.scout_harness.tools.scratchpad import remember  # noqa: PLC0415

    remember(
        team_id=verification.team_id,
        key=f"{FIX_OUTCOME_MEMORY_KEY_PREFIX}{report.id}",
        content=memory,
    )
    _prune_fix_outcome_memory(verification.team_id)


def _prune_fix_outcome_memory(team_id: int) -> None:
    stale_ids = list(
        SignalScratchpad.objects.for_team(team_id)
        .filter(key__startswith=FIX_OUTCOME_MEMORY_KEY_PREFIX)
        .order_by("-updated_at")
        .values_list("id", flat=True)[MAX_FIX_OUTCOME_MEMORY_ENTRIES:]
    )
    if stale_ids:
        SignalScratchpad.objects.for_team(team_id).filter(id__in=stale_ids).delete()
