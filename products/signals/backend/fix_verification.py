"""Post-merge fix verification: the outcome half of the signals autonomy loop.

Resolution says "a fix PR merged"; this module owns whether the fix actually held.
`schedule_fix_verification` records the pending claim when the tasks GitHub webhook
resolves a report; the verification sweep (temporal) settles it after the soak window.
"""

import uuid
from datetime import timedelta

from django.utils import timezone

import structlog

from products.signals.backend.models import SignalFixVerification, SignalReport

logger = structlog.get_logger(__name__)

# How long a resolved report must stay quiet after its fix PR merges before the fix
# counts as verified. Recurrences flip the row to REGRESSED as soon as the sweep sees
# them; only the VERIFIED outcome waits for this deadline.
FIX_VERIFICATION_SOAK_WINDOW = timedelta(days=7)


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
