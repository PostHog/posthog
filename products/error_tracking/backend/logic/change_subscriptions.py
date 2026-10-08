"""Subscriptions to issue changes: what they match, the data they need, where they deliver.

The change dispatcher matches each claimed change against every subscription, loads the
union of the matched subscriptions' needs once per team, and hands each subscription its
changes. A sink either delivers inline (cheap, in the dispatch batch) or starts one
Temporal workflow per change, for work that is slow, delayed or retried on its own.

A sink returns the changes it could not deliver for a transient reason; the dispatcher
leaves those in the outbox for the next run. Any exception a sink or a loader raises is
treated as permanent, so a change that cannot be processed never blocks the outbox.
"""

import asyncio
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from django.utils import timezone

import structlog
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect

from products.error_tracking.backend.logic.assignees import (
    ResolvedAssignee,
    resolve_current_assignees,
    resolve_user_assignees,
)
from products.error_tracking.backend.logic.issue_changes import AssigneeRef
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueChange,
    ErrorTrackingIssueFingerprintV2,
)

logger = structlog.get_logger(__name__)

Kind = ErrorTrackingIssueChange.Kind

WORKFLOW_START_TIMEOUT = timedelta(seconds=10)
WORKFLOW_START_CONCURRENCY = 8


class Need(StrEnum):
    DESCRIPTION = "description"
    FINGERPRINT = "fingerprint"
    # The issue's assignee now, with display values.
    CURRENT_ASSIGNEE = "current_assignee"
    # Display values for the users that change snapshots name as assignee.
    SNAPSHOT_ASSIGNEE_USER = "snapshot_assignee_user"
    ACTOR = "actor"


@frozen
class ChangeContext:
    """Data loaded for one team's matched changes. A mapping stays empty unless its need was requested."""

    team_id: int
    descriptions: Mapping[UUID, str | None]
    fingerprints: Mapping[UUID, str]
    current_assignees: Mapping[UUID, ResolvedAssignee]
    snapshot_assignee_users: Mapping[int, ResolvedAssignee]
    actors: Mapping[int, User]


@frozen
class Delivery:
    change: ErrorTrackingIssueChange
    context: ChangeContext


class InlineSink(Protocol):
    def deliver(self, deliveries: Sequence[Delivery]) -> set[UUID]:
        """Deliver within the dispatch batch. Returns the change ids that were not delivered."""
        ...


@frozen
class WorkflowSink:
    """Start one workflow per change. The workflow loads its own data from the references it receives."""

    workflow: str
    task_queue: str
    # Delay from the change, not from dispatch, so a backlog does not stretch it.
    start_delay: timedelta = timedelta(0)


@frozen
class Subscription:
    # Stable: it is part of every workflow id this subscription starts.
    key: str
    kinds: frozenset[Kind]
    sink: InlineSink | WorkflowSink
    needs: frozenset[Need] = frozenset()
    matches: Callable[[ErrorTrackingIssueChange], bool] | None = None

    def accepts(self, change: ErrorTrackingIssueChange) -> bool:
        return change.kind in self.kinds and (self.matches is None or self.matches(change))


# Temporal payloads are capped, so a workflow gets references and loads the rest itself.
@dataclass(frozen=True)
class ChangeWorkflowInputs:
    team_id: int
    change_id: str
    issue_id: str
    kind: str
    operation_id: str
    event_uuid: str | None
    event_timestamp: str | None


def load_change_context(
    team_id: int, changes: Collection[ErrorTrackingIssueChange], needs: Collection[Need]
) -> ChangeContext:
    issue_ids = {change.issue_id for change in changes}
    descriptions: Mapping[UUID, str | None] = {}
    fingerprints: Mapping[UUID, str] = {}
    current_assignees: Mapping[UUID, ResolvedAssignee] = {}
    snapshot_assignee_users: Mapping[int, ResolvedAssignee] = {}
    actors: Mapping[int, User] = {}

    if Need.DESCRIPTION in needs:
        descriptions = dict(
            ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids).values_list("id", "description")
        )
    if Need.FINGERPRINT in needs:
        # Same pick as the lifecycle event producer: the earliest fingerprint, with the id as tiebreaker.
        fingerprints = dict(
            ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id__in=issue_ids)
            .order_by("issue_id", "first_seen", "id")
            .distinct("issue_id")
            .values_list("issue_id", "fingerprint")
        )
    if Need.CURRENT_ASSIGNEE in needs:
        current_assignees = resolve_current_assignees(list(issue_ids))
    if Need.SNAPSHOT_ASSIGNEE_USER in needs:
        user_ids = {
            int(ref.id)
            for change in changes
            if (ref := AssigneeRef.from_json(change.snapshot.get("assignee"))) is not None and ref.type == "user"
        }
        if user_ids:
            organization_id = Team.objects.only("organization_id").get(id=team_id).organization_id
            snapshot_assignee_users = resolve_user_assignees(organization_id, user_ids)
    if Need.ACTOR in needs:
        actor_ids = {change.actor_user_id for change in changes if change.actor_user_id is not None}
        actors = {user.id: user for user in User.objects.filter(id__in=actor_ids)}

    return ChangeContext(
        team_id=team_id,
        descriptions=descriptions,
        fingerprints=fingerprints,
        current_assignees=current_assignees,
        snapshot_assignee_users=snapshot_assignee_users,
        actors=actors,
    )


def workflow_id_for(subscription_key: str, change_id: UUID) -> str:
    return f"error-tracking-change-{subscription_key}-{change_id}"


def start_change_workflows(subscription: Subscription, changes: Sequence[ErrorTrackingIssueChange]) -> set[UUID]:
    """Start the subscription's workflow for each change. Returns the change ids whose start was not accepted."""
    if not isinstance(subscription.sink, WorkflowSink) or not changes:
        return set()
    return asyncio.run(_connect_and_start(subscription.key, subscription.sink, changes))


async def _connect_and_start(
    subscription_key: str, sink: WorkflowSink, changes: Sequence[ErrorTrackingIssueChange]
) -> set[UUID]:
    try:
        temporal = await asyncio.wait_for(async_connect(), timeout=WORKFLOW_START_TIMEOUT.total_seconds())
    except Exception:
        logger.exception("error_tracking_change_workflow_connect_failed", subscription=subscription_key)
        return {change.id for change in changes}
    limit = asyncio.Semaphore(WORKFLOW_START_CONCURRENCY)
    accepted = await asyncio.gather(
        *(_start_one(temporal, subscription_key, sink, change, limit) for change in changes)
    )
    return {change.id for change, ok in zip(changes, accepted) if not ok}


async def _start_one(
    temporal: Client,
    subscription_key: str,
    sink: WorkflowSink,
    change: ErrorTrackingIssueChange,
    limit: asyncio.Semaphore,
) -> bool:
    inputs = ChangeWorkflowInputs(
        team_id=change.team_id,
        change_id=str(change.id),
        issue_id=str(change.issue_id),
        kind=change.kind,
        operation_id=str(change.operation_id),
        event_uuid=str(change.event_uuid) if change.event_uuid else None,
        event_timestamp=change.event_timestamp.isoformat() if change.event_timestamp else None,
    )
    start_delay = max(change.created_at + sink.start_delay - timezone.now(), timedelta(0))
    async with limit:
        try:
            await asyncio.wait_for(
                temporal.start_workflow(
                    sink.workflow,
                    inputs,
                    id=workflow_id_for(subscription_key, change.id),
                    task_queue=sink.task_queue,
                    # A redelivered start after the first run completed must be a no-op.
                    # A failed run stays retryable by a fresh start.
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    start_delay=start_delay if start_delay > timedelta(0) else None,
                ),
                timeout=WORKFLOW_START_TIMEOUT.total_seconds(),
            )
        except WorkflowAlreadyStartedError:
            return True
        except Exception:
            logger.exception(
                "error_tracking_change_workflow_start_failed",
                subscription=subscription_key,
                team_id=change.team_id,
                change_id=str(change.id),
            )
            return False
    return True
