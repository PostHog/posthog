"""Issue status from the workflow state of linked Linear tickets.

An issue resolves when every linked Linear ticket is closed and at least one of them is done. A
canceled ticket alone never resolves an issue, because it means nobody fixed anything. A resolved
issue becomes active again when a linked ticket moves from a closed state back to an open one.

A delivery only says that one ticket changed state. The task reads the current state of every
linked ticket from Linear before it decides, so a late or reordered delivery cannot apply a state
that the tickets no longer have.
"""

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from posthog.event_usage import groups
from posthog.ingress.contracts import DeliveryOwnership
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.models.activity_logging.activity_log import Trigger
from posthog.models.integration import Integration, LinearIntegration
from posthog.ph_client import ph_scoped_capture

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic.issue_mutations import transition_issue_status_by_automation
from products.error_tracking.backend.models import ErrorTrackingExternalReference, ErrorTrackingIssue

# Linear groups every workflow state into one of these categories. A team can rename its states
# and add more of them, but it cannot add a category, so the category is what the sync reads.
_DONE_STATE_TYPE = "completed"
_CLOSED_STATE_TYPES = frozenset({_DONE_STATE_TYPE, "canceled"})
_OPEN_STATE_TYPES = frozenset({"triage", "backlog", "unstarted", "started"})

_TRIGGER_JOB_TYPE = "linear_status_sync"

_WORKSPACE_LOOKUP_TIMEOUT_MS = 800


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
    issues = (
        ErrorTrackingIssue.objects.filter(
            external_issue__integration__kind=Integration.IntegrationKind.LINEAR.value,
            external_issue__integration__integration_id=job.organization_id,
            external_issue__external_context__id__in=job.identifiers,
        )
        .distinct()
        .select_related("team__organization")
    )

    previous_state = _PreviousStateType(job)
    for issue in issues:
        _sync_issue(issue, job, previous_state)


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
