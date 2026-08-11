"""Deletes inline scanners that never produced an observation.

An inline scan mints a scanner only once something is going to start, but a scan can still fail to
start after that: the org runs out of quota between the check and the claim, every workflow start
fails, or the caller retries with a config nobody ever asks about again. Those rows are permanent,
invisible, and worthless.

Only childless rows are reaped, so this can never delete a result. A row that produced observations is
somebody's answer to a question and stays until its observations do.
"""

from django.db.models import Exists, OuterRef
from django.utils import timezone

from temporalio import activity

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.enqueue_claims import pending_enqueue_claims_for_scanner
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerOrigin
from products.replay_vision.backend.temporal.constants import INLINE_SCANNER_REAP_BATCH_SIZE, INLINE_SCANNER_REAP_GRACE
from products.replay_vision.backend.temporal.decorators import track_activity


@database_sync_to_async
def _reap_childless_inline_scanners() -> int:
    # The grace period covers the gap between minting a scanner and its first observation row landing,
    # which spans a Temporal workflow start and an activity.
    cutoff = timezone.now() - INLINE_SCANNER_REAP_GRACE
    candidates = list(
        ReplayScanner.all_origins.filter(origin=ScannerOrigin.INLINE, created_at__lt=cutoff)
        .annotate(has_observations=Exists(ReplayObservation.objects.filter(scanner_id=OuterRef("pk"))))
        .filter(has_observations=False)
        .values_list("id", flat=True)[:INLINE_SCANNER_REAP_BATCH_SIZE]
    )
    if not candidates:
        return 0
    # A childless scanner can still have a scan in flight: reuse resolves an old row, starts a workflow,
    # and the observation only lands once create_observation runs. That gap is what enqueue claims
    # cover, so a claimed scanner is off limits even though it has nothing to show yet. Without this,
    # reaping mid-gap deletes the scanner out from under an accepted scan and the workflow fails with
    # the scanner missing. Candidates are normally empty, so this costs no Redis calls in the common case.
    unclaimed = [sid for sid in candidates if pending_enqueue_claims_for_scanner(sid) == 0]
    if not unclaimed:
        return 0
    # Re-check emptiness in the DELETE itself: an observation can land between the two statements, and
    # the FK cascade would take it with the scanner.
    deleted, _ = (
        ReplayScanner.all_origins.filter(id__in=unclaimed)
        .exclude(id__in=ReplayObservation.objects.filter(scanner_id__in=unclaimed).values("scanner_id"))
        .delete()
    )
    return deleted


@activity.defn
@track_activity()
async def reap_childless_inline_scanners_activity() -> int:
    deleted = await _reap_childless_inline_scanners()
    if deleted:
        activity.logger.info("Reaped childless inline scanners", extra={"deleted": deleted})
    return deleted
