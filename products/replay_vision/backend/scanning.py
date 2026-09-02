"""Starting scans, independent of who asked.

The API and Max both need to answer the same questions before a scan runs: how many new scans fit under
the in-flight caps and the monthly credit budget, which sessions are already settled, and which scanner
an inline config resolves to. That logic lives here so there is one copy of it, and callers are left to
translate the outcome into their own shape (a DRF response, a sentence for a chat).

Nothing here checks consent or access. Callers do that, because the answer differs: the API raises, Max
explains.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from django.db import IntegrityError, transaction

from posthog.models.team import Team
from posthog.models.user import User

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.enqueue_claims import (
    pending_enqueue_claims_for_scanner,
    pending_enqueue_claims_for_team,
    release_enqueue_claim,
)
from products.replay_vision.backend.inline_scan import create_inline_scanner, find_inline_scanner, inline_scan_key
from products.replay_vision.backend.models.replay_observation import TERMINAL_STATUSES, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.quota import compute_scanner_budget, quota_state
from products.replay_vision.backend.scanner_config import scanner_config_error
from products.replay_vision.backend.temporal.constants import (
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
    build_apply_scanner_workflow_id,
)

# One page of recordings. Above this the in-flight caps bind long before the batch does.
MAX_SESSIONS_PER_SCAN = 200


@dataclass(frozen=True, kw_only=True)
class ScanHeadroom:
    """What `scan_headroom` worked out, kept together so a request computes it once.

    Keyword-only because `team_rows` and `scanner_rows` are both counts of in-flight observations, and
    swapping them would silently loosen one of the two caps.
    """

    max_starts: int
    skip_reason: str
    team_rows: int
    scanner_rows: int


@dataclass(frozen=True, kw_only=True)
class InlineScanResult:
    """`scanner` is None when nothing could start and none existed, so there is nothing to read back."""

    scanner: ReplayScanner | None
    started: int
    results: list[dict[str, str]]


def scan_headroom(*, team: Team, model: str, scanner: ReplayScanner | None) -> ScanHeadroom:
    """How many new scans can start, the reason once that's used up, and the row counts the per-start
    slot claims reuse.

    `scanner=None` asks the same question for a config that has no scanner yet, so an inline scan can
    decide whether minting one is worth it. The per-scanner terms are zero by definition there, which is
    also why the caller can pass the answer straight into `start_observations`.
    """
    team_in_flight = ReplayObservation.in_flight_for_team(team.id).count()
    scanner_in_flight = 0
    scanner_claims = 0
    if scanner is not None:
        scanner_in_flight = ReplayObservation.in_flight_for_team(team.id).filter(scanner_id=scanner.id).count()
        scanner_claims = pending_enqueue_claims_for_scanner(scanner.id)
    # Enqueued-but-not-yet-persisted scans hold claims instead of rows.
    in_flight_limit = max(
        0,
        min(
            MAX_IN_FLIGHT_APPLIES_PER_SCANNER - scanner_in_flight - scanner_claims,
            MAX_IN_FLIGHT_APPLIES_PER_TEAM - team_in_flight - pending_enqueue_claims_for_team(team.id),
        ),
    )
    snapshot = quota_state(team.organization_id)
    cost = observation_credits_for_model(model)
    # None means nothing binds: an uncapped org (or scanner), or a free model that spends nothing.
    affordable = snapshot.affordable_count(cost)
    quota_limit = in_flight_limit if affordable is None else affordable
    scanner_affordable = compute_scanner_budget(scanner).affordable_count(cost) if scanner is not None else None
    scanner_limit = in_flight_limit if scanner_affordable is None else scanner_affordable
    # Report whichever limit is strictly tighter, so the user knows which one to raise.
    if scanner_limit < in_flight_limit and scanner_limit <= quota_limit:
        return ScanHeadroom(
            max_starts=scanner_limit,
            skip_reason="skipped_scanner_limit",
            team_rows=team_in_flight,
            scanner_rows=scanner_in_flight,
        )
    if quota_limit < in_flight_limit:
        return ScanHeadroom(
            max_starts=quota_limit,
            skip_reason="skipped_quota",
            team_rows=team_in_flight,
            scanner_rows=scanner_in_flight,
        )
    return ScanHeadroom(
        max_starts=in_flight_limit,
        skip_reason="skipped_limit",
        team_rows=team_in_flight,
        scanner_rows=scanner_in_flight,
    )


def finished_sessions(scanner: ReplayScanner, session_ids: list[str]) -> frozenset[str]:
    """Sessions this scanner already settled on.

    A terminal observation makes (scanner, session) permanently taken, so starting a workflow for one
    would burn a run only to lose the INSERT and hand back the row we can already see.
    """
    return frozenset(
        ReplayObservation.objects.filter(
            scanner_id=scanner.id,
            session_id__in=session_ids,
            status__in=TERMINAL_STATUSES,
        ).values_list("session_id", flat=True)
    )


def start_observations(
    *,
    scanner: ReplayScanner,
    session_ids: list[str],
    user: User,
    headroom: ScanHeadroom,
    finished: frozenset[str],
) -> tuple[int, list[dict[str, str]]]:
    """Start a scan per session, as many as fit. Returns (started, per-session outcomes).

    "Scan what fits": the caller works out how many NEW scans can start once, up front, and passes it in
    so a request takes the quota snapshot only once. The tighter of the in-flight caps and the remaining
    monthly quota bounds it; the loser names the skip reason so the user knows which limit they hit.
    Decrementing a local counter as we start models each new in-flight row without re-querying (a
    started scan consumes exactly one slot).
    """
    # Imported here to break the cycle: trigger imports quota, which imports prompt_evaluation, which
    # reaches temporal, whose activities import this module.
    from products.replay_vision.backend.api.trigger import (  # noqa: PLC0415
        WorkflowStartOutcome,
        start_apply_scanner_workflow,
    )
    from products.replay_vision.backend.models.replay_observation import ObservationTrigger  # noqa: PLC0415

    max_starts, skip_reason = headroom.max_starts, headroom.skip_reason
    results: list[dict[str, str]] = []
    started = 0
    for session_id in session_ids:
        # Checked before the cap so a settled session reports what it is rather than being reported as
        # skipped, and consumes no headroom. `start_apply_scanner_workflow` enforces the same rule for
        # callers that don't prefetch.
        if session_id in finished:
            results.append({"session_id": session_id, "scan_outcome": "already_scanned"})
            continue
        if started >= max_starts:
            results.append({"session_id": session_id, "scan_outcome": skip_reason})
            continue
        _, outcome = start_apply_scanner_workflow(
            scanner,
            session_id,
            triggered_by_user_id=user.id,
            trigger=ObservationTrigger.ON_DEMAND,
            # Row counts are this request's snapshot; the atomic claim inside makes racing requests
            # visible to each other, which the snapshot alone cannot.
            team_in_flight_rows=headroom.team_rows,
            scanner_in_flight_rows=headroom.scanner_rows,
            finished_sessions=finished,
        )
        if outcome is WorkflowStartOutcome.STARTED:
            started += 1
            results.append({"session_id": session_id, "scan_outcome": "started"})
        elif outcome is WorkflowStartOutcome.ALREADY_SCANNED:
            # The prefetched set was taken before the loop, so a session can settle mid-batch.
            results.append({"session_id": session_id, "scan_outcome": "already_scanned"})
        elif outcome is WorkflowStartOutcome.ALREADY_RUNNING:
            # Already in flight — counted in the caps already, so it consumes no new headroom.
            results.append({"session_id": session_id, "scan_outcome": "already_running"})
        elif outcome is WorkflowStartOutcome.CAPPED:
            # A racing request consumed the remaining slots, so the in-flight cap binds the rest.
            results.append({"session_id": session_id, "scan_outcome": "skipped_limit"})
            max_starts = started
            skip_reason = "skipped_limit"
        else:
            results.append({"session_id": session_id, "scan_outcome": "failed"})
    return started, results


def scan_existing_scanner(
    *, scanner: ReplayScanner, session_ids: list[str], user: User
) -> tuple[int, list[dict[str, str]]]:
    """Point a saved scanner at named sessions."""
    return start_observations(
        scanner=scanner,
        session_ids=session_ids,
        user=user,
        headroom=scan_headroom(team=scanner.team, model=scanner.model, scanner=scanner),
        finished=finished_sessions(scanner, session_ids),
    )


def run_inline_scan(
    *,
    team: Team,
    user: User,
    session_ids: list[str],
    scanner_type: ScannerType,
    scanner_config: dict[str, Any],
    model: str,
) -> InlineScanResult:
    """Scan named sessions against a config nobody saved (see `inline_scan.py` for why a scanner exists).

    Raises ValueError on a config or batch the API layer would have rejected. Enforced here rather than
    only in the serializer because the config is persisted on the scanner and copied into every
    observation snapshot, so a caller that skips DRF must not be able to write one.
    """
    if len(session_ids) > MAX_SESSIONS_PER_SCAN:
        raise ValueError(f"At most {MAX_SESSIONS_PER_SCAN} sessions can be scanned at once.")
    config_error = scanner_config_error(scanner_type, scanner_config)
    if config_error is not None:
        raise ValueError(config_error)
    key = inline_scan_key(scanner_type=scanner_type, scanner_config=scanner_config, model=model)
    scanner = find_inline_scanner(team=team, key=key)
    headroom = scan_headroom(team=team, model=model, scanner=scanner)
    if scanner is None:
        # Mint only once something can actually start, so an org with no headroom doesn't leave a
        # scanner behind for every question it was unable to answer.
        if headroom.max_starts <= 0:
            return InlineScanResult(
                scanner=None,
                started=0,
                results=[{"session_id": s, "scan_outcome": headroom.skip_reason} for s in session_ids],
            )
        scanner = create_inline_scanner(
            team=team,
            key=key,
            scanner_type=scanner_type,
            scanner_config=scanner_config,
            model=model,
        )
        # A scanner that did not exist a statement ago has no observations to have settled.
        finished: frozenset[str] = frozenset()
    else:
        finished = finished_sessions(scanner, session_ids)

    started, results = start_observations(
        scanner=scanner, session_ids=session_ids, user=user, headroom=headroom, finished=finished
    )
    return InlineScanResult(scanner=scanner, started=started, results=results)


class RetryOutcome(Enum):
    STARTED = "started"
    # Succeeded observations already have their answer; only failed and ineligible ones are retryable.
    NOT_RETRYABLE = "not_retryable"
    # The prior run is still closing, so its deterministic workflow id blocks the restart.
    ALREADY_RUNNING = "already_running"
    CAPPED = "capped"
    FAILED = "failed"


def retry_observation(*, observation: ReplayObservation, user: User) -> tuple[RetryOutcome, str]:
    """Delete a failed or ineligible observation and scan the same recording again.

    The row has to go because UNIQUE(scanner, session_id) would otherwise lock the session out of that
    scanner forever, and the delete cascades the team's rating with it. So the rating is captured first
    and put back, timestamps and all, whenever the replacement run doesn't start: a retry that changes
    nothing must leave the recording exactly as it found it.
    """
    from products.replay_vision.backend.api.trigger import (  # noqa: PLC0415
        WorkflowStartOutcome,
        check_observation_quota,
        check_scanner_quota,
        check_team_in_flight_capacity,
        claim_apply_scanner_slot,
        start_apply_scanner_workflow,
    )
    from products.replay_vision.backend.models.replay_observation import (  # noqa: PLC0415
        ObservationStatus,
        ObservationTrigger,
    )
    from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel  # noqa: PLC0415

    scanner = observation.scanner
    session_id = observation.session_id
    original_pk = observation.pk
    original_created_at = observation.created_at
    # Ineligible is retryable because some gates are timing artifacts: the recording or its snapshots can
    # finish ingesting after the scan ran (see IneligibleSessionKind.NO_SNAPSHOTS).
    workflow_id = build_apply_scanner_workflow_id(scanner.id, session_id)
    if observation.status not in (ObservationStatus.FAILED, ObservationStatus.INELIGIBLE):
        return RetryOutcome.NOT_RETRYABLE, workflow_id
    # Advisory, and deliberately outside the lock below: the atomic claim is the authoritative gate, and
    # these two read enough to be worth keeping off a held row lock.
    # Raises QuotaLimitExceeded / Throttled, which callers already know how to render. Kept as
    # exceptions rather than outcomes so the API's existing 402 and 429 messages are unchanged.
    check_observation_quota(scanner.team.organization_id, observation_credits_for_model(scanner.model))
    check_scanner_quota(scanner)
    check_team_in_flight_capacity(scanner.team_id)

    # Locked so two concurrent retries can't both pass the status check and both delete the row.
    with transaction.atomic():
        locked = ReplayObservation.objects.select_for_update().get(pk=original_pk, team_id=scanner.team_id)
        if locked.status not in (ObservationStatus.FAILED, ObservationStatus.INELIGIBLE):
            return RetryOutcome.NOT_RETRYABLE, workflow_id
        # Captured before the delete cascades it away: a run that never starts has to put the team's
        # rating back with the row, not just the row.
        original_label = ReplayObservationLabel.objects.filter(
            observation_id=original_pk, team_id=locked.team_id
        ).first()
        label_created_at = original_label.created_at if original_label else None
        label_updated_at = original_label.updated_at if original_label else None
        # Claimed before the delete so a capped retry never touches the row, and so never cascades away
        # the observation's shared label for a request that changes nothing.
        _, claimed = claim_apply_scanner_slot(scanner, session_id)
        if not claimed:
            return RetryOutcome.CAPPED, workflow_id
        try:
            # Free the UNIQUE(scanner, session_id) slot; the ledger is immutable, so the failed attempt
            # stays counted.
            locked.delete()
        except Exception:
            release_enqueue_claim(
                team_id=scanner.team_id, scanner_id=scanner.id, workflow_id=workflow_id, immediately=True
            )
            raise

    _, outcome = start_apply_scanner_workflow(
        scanner,
        session_id,
        triggered_by_user_id=user.id,
        trigger=ObservationTrigger.RETRY,
        slot_already_claimed=True,
    )
    if outcome is not WorkflowStartOutcome.STARTED:
        # The replacement run never started, so restore the original row and its rating instead of
        # leaving the recording looking unscanned and the team's feedback gone.
        try:
            with transaction.atomic():
                observation.pk = original_pk
                observation.save(force_insert=True)
                ReplayObservation.objects.filter(pk=original_pk, team_id=observation.team_id).update(
                    created_at=original_created_at
                )
                if original_label is not None:
                    original_label.save(force_insert=True)
                    # auto_now_add/auto_now stamp the insert with now; the rating happened earlier.
                    ReplayObservationLabel.objects.filter(pk=original_label.pk, team_id=observation.team_id).update(
                        created_at=label_created_at, updated_at=label_updated_at
                    )
        except IntegrityError:
            # A run we couldn't start is already persisting its own row for this (scanner, session); the
            # recording isn't stranded, so report it as still finishing rather than failing hard.
            outcome = WorkflowStartOutcome.ALREADY_RUNNING

    if outcome is WorkflowStartOutcome.ALREADY_RUNNING:
        return RetryOutcome.ALREADY_RUNNING, workflow_id
    if outcome is WorkflowStartOutcome.STARTED:
        return RetryOutcome.STARTED, workflow_id
    return RetryOutcome.FAILED, workflow_id
