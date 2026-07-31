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

from products.signals.backend.artefact_schemas import RelatedTo, parse_artefact_content
from products.signals.backend.models import SignalFixVerification, SignalReport, SignalReportArtefact

logger = structlog.get_logger(__name__)

# How long a resolved report must stay quiet after its fix PR merges before the fix
# counts as verified. Recurrences flip the row to REGRESSED as soon as the sweep sees
# them; only the VERIFIED outcome waits for this deadline.
FIX_VERIFICATION_SOAK_WINDOW = timedelta(days=7)

# Per-sweep cap so a backlog (first deploy, sweep outage) settles over a few ticks
# instead of one unbounded pass.
FIX_VERIFICATION_SWEEP_LIMIT = 500


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
        outcome = _settle_verification(verification, now=now)
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
    """The first still-live report the grouping pipeline linked to `report` after the merge."""
    link_artefacts = SignalReportArtefact.objects.filter(
        report_id=report.id,
        type=SignalReportArtefact.ArtefactType.RELATED_TO,
        created_at__gt=verification.created_at,
    ).order_by("created_at")

    linked_ids: list[str] = []
    for artefact in link_artefacts:
        content = parse_artefact_content(artefact.type, artefact.content)
        if isinstance(content, RelatedTo):
            linked_ids.append(content.report_id)
    if not linked_ids:
        return None

    live_by_id = {
        str(r.id): r
        for r in SignalReport.objects.filter(id__in=linked_ids, team_id=verification.team_id).exclude(
            status__in=[SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED]
        )
    }
    for linked_id in linked_ids:
        if linked_id in live_by_id:
            return live_by_id[linked_id]
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
    return status
