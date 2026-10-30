"""Issue status from the workflow state of linked Linear tickets.

An issue resolves when every linked Linear ticket is closed and at least one of them is done. A
canceled ticket alone never resolves an issue, because it means nobody fixed anything. A resolved
issue becomes active again when a linked ticket moves from a closed state back to an open one.
Only projects that turn on `linear_status_sync_enabled` in their error tracking settings take part.

A delivery only says that one ticket changed state. The task reads the current state of every
linked ticket from Linear before it decides, so a late or reordered delivery cannot apply a state
that the tickets no longer have.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from redis.exceptions import LockError, LockNotOwnedError

from posthog.event_usage import groups
from posthog.ingress.contracts import DeliveryOwnership
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.models.activity_logging.activity_log import Trigger
from posthog.models.integration import Integration, LinearIntegration, LinearRateLimitedError
from posthog.ph_client import ph_scoped_capture
from posthog.redis import get_client

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic.issue_mutations import transition_issue_status_by_automation
from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingSettings,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

# Linear groups every workflow state into one of these categories. A team can rename its states
# and add more of them, but it cannot add a category, so the category is what the sync reads.
_DONE_STATE_TYPE = "completed"
_CLOSED_STATE_TYPES = frozenset({_DONE_STATE_TYPE, "canceled"})
_OPEN_STATE_TYPES = frozenset({"triage", "backlog", "unstarted", "started"})

_TRIGGER_JOB_TYPE = "linear_status_sync"

_WORKSPACE_LOOKUP_TIMEOUT_MS = 800

# Long enough to read every linked ticket of one issue. A job that dies holding the lock frees it then.
_ISSUE_LOCK_TIMEOUT_SECONDS = 120
_ISSUE_LOCK_WAIT_SECONDS = 10

logger = structlog.get_logger(__name__)


def prepare_job(payload: Mapping[str, Any]) -> contracts.LinearStatusSyncJob | None:
    if payload.get("type") != "Issue" or payload.get("action") != "update":
        return None
    organization_id = payload.get("organizationId")
    data = payload.get("data")
    updated_from = payload.get("updatedFrom")
    if not isinstance(organization_id, str) or not isinstance(data, Mapping) or not isinstance(updated_from, Mapping):
        return None
    identifier = data.get("identifier")
    # Linear lists only the fields an update changed in `updatedFrom`, so `stateId` is there
    # exactly when the ticket moved to another workflow state.
    previous_state_id = updated_from.get("stateId")
    if not organization_id or not isinstance(identifier, str) or not identifier:
        return None
    if not isinstance(previous_state_id, str) or not previous_state_id:
        return None

    # A reference stores the identifier the ticket had when it was linked, and a ticket that
    # moved to another Linear team has a new one.
    previous_identifiers = data.get("previousIdentifiers")
    identifiers = [identifier]
    if isinstance(previous_identifiers, list):
        identifiers.extend(value for value in previous_identifiers if isinstance(value, str) and value)
    return contracts.LinearStatusSyncJob(
        organization_id=organization_id,
        identifiers=tuple(dict.fromkeys(identifiers)),
        previous_state_id=previous_state_id,
    )


def delivery_ownership(payload: Mapping[str, Any]) -> DeliveryOwnership:
    """Which region holds the Linear workspace that a state change comes from.

    One Linear App serves both regions, so every delivery reaches the receiving region first. A
    workspace that no team here connects is `ELSEWHERE`, because only the other region can tell a
    workspace it holds from one that nobody holds. A delivery that changes no workflow state is
    `UNDECIDED`: no region acts on it, so the ticket's contents do not cross the region boundary.
    A lookup that raises is let out, so Linear sends the delivery again instead of it going to a
    region on a guess.
    """
    job = prepare_job(payload)
    if job is None:
        return DeliveryOwnership.UNDECIDED
    with bounded_statement_timeout(_WORKSPACE_LOOKUP_TIMEOUT_MS, models=[Integration]):
        held_here = Integration.objects.filter(
            kind=Integration.IntegrationKind.LINEAR.value, integration_id=job.organization_id
        ).exists()
    return DeliveryOwnership.LOCAL if held_here else DeliveryOwnership.ELSEWHERE


def sync_status(job: contracts.LinearStatusSyncJob) -> None:
    opted_in_team_ids = _opted_in_team_ids(job)
    _refresh_moved_identifiers(job, opted_in_team_ids)
    issues = (
        ErrorTrackingIssue.objects.filter(
            team_id__in=opted_in_team_ids,
            external_issue__integration__kind=Integration.IntegrationKind.LINEAR.value,
            external_issue__integration__integration_id=job.organization_id,
            external_issue__external_context__id__in=job.identifiers,
        )
        .distinct()
        .order_by("id")
        .select_related("team__organization")
    )

    # Each project reads Linear with its own token, so one revoked token must not keep every other
    # project's issue from syncing. One failure is raised after the loop so the task retries, and a
    # retry is a no-op for the issues that already changed.
    previous_state = _PreviousStateType(job)
    failures: list[Exception] = []
    for issue in issues:
        try:
            with _issue_lock(issue.id):
                _sync_issue(issue, job, previous_state)
        except Exception as error:
            logger.warning("linear_status_sync_issue_failed", issue_id=str(issue.id), team_id=issue.team_id)
            failures.append(error)
    if failures:
        raise _failure_to_retry(failures)


@contextmanager
def _issue_lock(issue_id: UUID) -> Iterator[None]:
    """Run one issue's Linear reads and status change while no other job does the same for it.

    A job reads the ticket states before it takes the issue row lock, so two overlapping jobs
    could act on their reads in the wrong order: a close job that read `completed` could resolve
    the issue after a reopen job read `started` and found nothing to reopen. Raises LockError
    while another job holds the issue, so the task retries it later.
    """
    lock = get_client().lock(
        f"error_tracking:linear_status_sync:{issue_id}",
        timeout=_ISSUE_LOCK_TIMEOUT_SECONDS,
        blocking_timeout=_ISSUE_LOCK_WAIT_SECONDS,
    )
    if not lock.acquire():
        raise LockError(f"Another Linear status sync holds issue {issue_id}")
    try:
        yield
    finally:
        # A job that outlived the lock timeout no longer owns it, and its work is already done.
        with suppress(LockNotOwnedError):
            lock.release()


def _failure_to_retry(failures: list[Exception]) -> Exception:
    """The failure that needs the longest wait, because the task picks its retry from the raised type.

    A rate limit comes first, because a retry before Linear resets the limit fails again. A busy
    issue comes next, because a job that died holding the lock keeps it for the lock timeout, and
    the generic retry budget runs out before that.
    """
    rate_limited = [failure for failure in failures if isinstance(failure, LinearRateLimitedError)]
    if rate_limited:
        return max(rate_limited, key=lambda failure: failure.retry_after_seconds)
    busy = [failure for failure in failures if isinstance(failure, LockError)]
    return busy[0] if busy else failures[0]


def _opted_in_team_ids(job: contracts.LinearStatusSyncJob) -> "QuerySet[ErrorTrackingSettings, int]":
    """The projects that connect the job's Linear workspace and turned the sync on."""
    return ErrorTrackingSettings.objects.filter(
        linear_status_sync_enabled=True,
        team_id__in=Integration.objects.filter(
            kind=Integration.IntegrationKind.LINEAR.value, integration_id=job.organization_id
        ).values("team_id"),
    ).values_list("team_id", flat=True)


def _refresh_moved_identifiers(
    job: contracts.LinearStatusSyncJob, opted_in_team_ids: "QuerySet[ErrorTrackingSettings, int]"
) -> None:
    """Point references that hold an identifier from before a team move at the ticket's current one.

    A reference stores only the identifier, and the state lookup finds a ticket by its current
    one, so a stale identifier reads as a deleted ticket and stops holding its issue open. Workflow
    states belong to a team, so a move between teams always changes the state and reaches here.
    """
    current, *previous = job.identifiers
    if not previous:
        return
    stale = ErrorTrackingExternalReference.objects.filter(
        issue__team_id__in=opted_in_team_ids,
        integration__kind=Integration.IntegrationKind.LINEAR.value,
        integration__integration_id=job.organization_id,
        external_context__id__in=previous,
    )
    for reference in stale:
        reference.external_context = {**(reference.external_context or {}), "id": current}
        reference.save(update_fields=["external_context"])


class _PreviousStateType:
    """The category of the state the ticket left, read from Linear at most once per job."""

    def __init__(self, job: contracts.LinearStatusSyncJob) -> None:
        self._job = job
        self._read = False
        self._value: str | None = None

    def get(self, integration: Integration) -> str | None:
        if not self._read:
            self._value = LinearIntegration(integration).workflow_state_type(self._job.previous_state_id)
            self._read = True
        return self._value


def _sync_issue(
    issue: ErrorTrackingIssue, job: contracts.LinearStatusSyncJob, previous_state: _PreviousStateType
) -> None:
    references = list(
        ErrorTrackingExternalReference.objects.filter(
            issue_id=issue.id, integration__kind=Integration.IntegrationKind.LINEAR.value
        ).select_related("integration")
    )
    trigger_identifiers = set(job.identifiers)

    def is_trigger(reference: ErrorTrackingExternalReference) -> bool:
        return (
            reference.integration.integration_id == job.organization_id
            and _stored_identifier(reference) in trigger_identifiers
        )

    trigger_references = [reference for reference in references if is_trigger(reference)]
    if not trigger_references:
        return

    states = _current_state_types(references, current_trigger_identifier=job.identifiers[0], is_trigger=is_trigger)
    trigger_state = states.get(trigger_references[0].id)
    trigger = Trigger(
        job_type=_TRIGGER_JOB_TYPE,
        job_id=job.identifiers[0],
        payload={"linear_issue": job.identifiers[0], "linear_state_type": trigger_state},
    )

    if trigger_state in _CLOSED_STATE_TYPES:
        # A ticket Linear no longer returns was deleted or cannot be read any more, so it does not
        # hold the issue open.
        known_states = set(states.values())
        if known_states <= _CLOSED_STATE_TYPES and _DONE_STATE_TYPE in known_states:
            _transition(
                issue,
                expected=ErrorTrackingIssue.Status.ACTIVE,
                status=ErrorTrackingIssue.Status.RESOLVED,
                trigger=trigger,
            )
    elif trigger_state in _OPEN_STATE_TYPES:
        # Only a move out of a closed state is a reopen. A ticket that moves from "Todo" to
        # "In Progress" must not reactivate an issue that someone resolved in PostHog.
        if previous_state.get(trigger_references[0].integration) in _CLOSED_STATE_TYPES:
            _transition(
                issue,
                expected=ErrorTrackingIssue.Status.RESOLVED,
                status=ErrorTrackingIssue.Status.ACTIVE,
                trigger=trigger,
            )


def _transition(
    issue: ErrorTrackingIssue,
    *,
    expected: ErrorTrackingIssue.Status,
    status: ErrorTrackingIssue.Status,
    trigger: Trigger,
) -> None:
    changed = transition_issue_status_by_automation(
        issue.team_id, issue.id, expected=expected, status=status, trigger=trigger
    )
    if not changed:
        return
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(issue.team.uuid),
            # pinned: analytics event name, renaming it breaks dashboards
            event="error_tracking_issue_status_synced_from_linear",
            properties={"status": status.value, "previous_status": expected.value},
            groups=groups(issue.team.organization, issue.team),
        )


def _stored_identifier(reference: ErrorTrackingExternalReference) -> str | None:
    identifier = (reference.external_context or {}).get("id")
    return identifier if isinstance(identifier, str) else None


def _current_state_types(
    references: list[ErrorTrackingExternalReference],
    *,
    current_trigger_identifier: str,
    is_trigger: Callable[[ErrorTrackingExternalReference], bool],
) -> dict[UUID, str]:
    """The current state category of each reference's ticket, keyed by reference id.

    A reference whose ticket Linear does not return is absent. The trigger ticket is read by the
    identifier it has now, because its reference can hold one from before a move between teams.
    """
    lookups: dict[int, tuple[Integration, dict[UUID, str]]] = {}
    for reference in references:
        identifier = current_trigger_identifier if is_trigger(reference) else _stored_identifier(reference)
        if identifier is None:
            continue
        _, by_reference = lookups.setdefault(reference.integration.id, (reference.integration, {}))
        by_reference[reference.id] = identifier

    states: dict[UUID, str] = {}
    for integration, by_reference in lookups.values():
        found = LinearIntegration(integration).issue_state_types(sorted(set(by_reference.values())))
        for reference_id, identifier in by_reference.items():
            if identifier in found:
                states[reference_id] = found[identifier]
    return states
