"""Alert delivery: one Slack thread per (alert, issue, destination).

Triggers gate thread openers only. A transition whose event satisfies one of an
alert's triggers opens a notification thread per destination: a root Slack
message whose `ts` is stored on the thread row. Every other lifecycle event is
delivered as a reply into that thread, without a second trigger or filter
evaluation, and status transitions also edit the root in place.

Delivery is at-least-once. A per-thread send claim serializes concurrent
deliveries so two notifications never post at the same time (the loser retries
into the winner's thread), and delivered notification ids recorded on the row make
a retry after a successful save a no-op. A crash between the Slack post and that
save still re-posts on retry. The alert's stored filters gate openers (see
filtering.py).
"""

import dataclasses
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError
from django.db.models import F, Q
from django.utils import timezone

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from temporalio.exceptions import ApplicationError

from posthog.models.integration import Integration, SlackIntegration
from posthog.redis import get_client

from products.error_tracking.backend.logic.alerts import MAX_THROTTLE_SECONDS
from products.error_tracking.backend.models import (
    ErrorTrackingAlert,
    ErrorTrackingAlertDestination,
    ErrorTrackingAlertThread,
)
from products.error_tracking.backend.temporal.alerts.filtering import (
    alert_filters_match,
    fetch_exception_properties,
    has_configured_filters,
)
from products.error_tracking.backend.temporal.alerts.messages import (
    DEFAULT_HEADLINE,
    build_reply_text,
    build_root_edit,
    build_root_message,
)
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs

logger = structlog.get_logger(__name__)

# Which lifecycle event satisfies which alert trigger. Only these open a thread;
# every other lifecycle event is delivered as a reply to an existing thread.
OPENER_TRIGGERS = {
    "$error_tracking_issue_created": ErrorTrackingAlert.Trigger.ISSUE_CREATED,
    "$error_tracking_issue_reopened": ErrorTrackingAlert.Trigger.ISSUE_REOPENED,
    "$error_tracking_issue_spiking": ErrorTrackingAlert.Trigger.ISSUE_SPIKING,
    "$error_tracking_issue_assigned": ErrorTrackingAlert.Trigger.ISSUE_ASSIGNED,
}

# Status transitions also update the root message in place. The headline stays:
# it is the thread's identity.
ROOT_EDIT_EVENTS = {
    "$error_tracking_issue_resolved",
    "$error_tracking_issue_suppressed",
    "$error_tracking_issue_reopened",
}

DELIVERED_NOTIFICATION_IDS_CAP = 200
# A send claim older than this belongs to a holder that died between posting and
# saving; the next delivery takes over. A live holder makes at most two Slack calls
# per thread (post, then root edit); each is up to two 30s attempts under the SDK's
# default connection-error retry, so ~130s worst case, and 240s cannot expire under
# a live holder. It must stay shorter than the activity retry schedule (workflow.py)
# so a busy loser is still retrying when it expires.
PENDING_CLAIM_TTL = timedelta(seconds=240)


class AlertThreadBusyError(Exception):
    """Another notification holds this thread's send claim; retry after it saves."""


ALERT_THROTTLE_KEY_PREFIX = "error_tracking:alert_throttle:v1"
_RELEASE_IF_HELD = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
MAX_RECORDED_ERROR_LENGTH = 500


# Slack error codes that no retry can fix: the bot was removed, the channel is gone
# or archived, or the token lost a scope. Recorded on the destination and skipped.
SLACK_TERMINAL_ERRORS = frozenset(
    {
        "not_in_channel",
        "account_inactive",
        "is_archived",
        "channel_not_found",
        "invalid_auth",
        "token_revoked",
        "missing_scope",
        "not_allowed_token_type",
        "not_authed",
        "no_permission",
        "org_login_required",
        "ekm_access_denied",
        "restricted_action",
        "team_access_not_granted",
        # token_expired is deliberately absent: Slack is an OAuth integration here and
        # the periodic refresh sweep replaces expired tokens, so a retry can succeed.
    }
)


class AlertDeliveryError(ApplicationError):
    def __init__(self, message: str, *, retry_after: timedelta | None = None) -> None:
        super().__init__(message, next_retry_delay=retry_after)


@dataclasses.dataclass(frozen=True)
class PlannedDelivery:
    """One (alert, destination) conversation this transition reaches."""

    alert: ErrorTrackingAlert
    destination: ErrorTrackingAlertDestination
    is_opener: bool
    thread: ErrorTrackingAlertThread | None


def plan_alert_deliveries(inputs: AlertDeliveryWorkflowInputs) -> list[PlannedDelivery]:
    trigger = OPENER_TRIGGERS.get(inputs.event)
    alerts = list(ErrorTrackingAlert.objects.for_team(inputs.team_id).filter(enabled=True))
    destinations_by_alert: dict = {}
    for destination in (
        ErrorTrackingAlertDestination.objects.for_team(inputs.team_id)
        .filter(alert__in=alerts)
        .select_related("integration")
    ):
        destinations_by_alert.setdefault(destination.alert_id, []).append(destination)
    # Threads are unique per (alert, issue, destination): a multi-destination alert
    # holds one independent conversation per destination.
    threads_by_destination = {
        thread.destination_id: thread
        for thread in ErrorTrackingAlertThread.objects.for_team(inputs.team_id).filter(issue_id=inputs.issue_id)
    }

    planned: list[PlannedDelivery] = []
    for alert in alerts:
        trigger_matched = trigger is not None and trigger in alert.triggers
        for destination in destinations_by_alert.get(alert.id, []):
            thread = threads_by_destination.get(destination.id)
            if thread is None and not trigger_matched:
                # Replies never open threads: an update with no rooted thread stays
                # unclaimed so a later opener can still start the conversation cleanly.
                continue
            # Only the first matching transition opens; once a destination has a
            # rooted thread, every later transition is a reply into it, even a
            # repeated opener event (e.g. spiking again, or reopen after resolve).
            # An unrooted row is a failed root post: the next opener roots it.
            rooted = thread is not None and bool(thread.external_ref.get("ts"))
            is_opener = trigger_matched and not rooted
            planned.append(PlannedDelivery(alert=alert, destination=destination, is_opener=is_opener, thread=thread))
    return planned


def _opener_filter_matches(
    planned: list[PlannedDelivery], inputs: AlertDeliveryWorkflowInputs
) -> dict[UUID, bool | None]:
    """Filters gate openers only, evaluated once per (transition, alert).

    Replies follow the thread without a second evaluation, so this only looks at
    alerts with a planned opener, and only fetches the triggering exception's
    properties when at least one of those alerts configures filters.
    """
    opener_alerts = {delivery.alert.id: delivery.alert for delivery in planned if delivery.is_opener}
    if not opener_alerts:
        return {}
    exception_properties: dict[str, object] = {}
    if any(has_configured_filters(alert) for alert in opener_alerts.values()):
        try:
            exception_properties = fetch_exception_properties(inputs)
        except Exception:
            # Filtered openers cannot be decided without the properties, but that
            # must not hold back alerts that never needed them: those deliver now,
            # the undecided ones fail the activity so the retry evaluates them.
            logger.exception(
                "error_tracking_alert_exception_properties_unavailable",
                team_id=inputs.team_id,
                issue_id=inputs.issue_id,
                notification_id=inputs.notification_id,
            )
            return {
                alert_id: (None if has_configured_filters(alert) else True) for alert_id, alert in opener_alerts.items()
            }
    return {
        alert_id: alert_filters_match(alert, inputs, exception_properties) for alert_id, alert in opener_alerts.items()
    }


def deliver_alert_notifications(inputs: AlertDeliveryWorkflowInputs) -> int:
    planned = plan_alert_deliveries(inputs)
    filter_matches = _opener_filter_matches(planned, inputs)
    throttle_allowed: dict = {}
    # Throttled alerts with an opener in this run, minus those that rooted a
    # conversation or are still owed a retry: the rest give their window back at
    # the end. Openers re-rooting an unrooted row count too, so a retry that
    # turns terminal releases the window its first attempt claimed.
    throttled_openers: dict = {}
    rooted: set = set()
    retrying: set = set()
    delivered = 0
    failures = 0
    retry_after = timedelta(0)
    for delivery in planned:
        if delivery.is_opener:
            verdict = filter_matches.get(delivery.alert.id, True)
            if verdict is None:
                # Undecided: the exception properties could not be fetched. Counted
                # as a failure so the activity retries once the rest has delivered.
                failures += 1
                continue
            if not verdict:
                # A filtered-out opener leaves no thread behind, so later replies for
                # this issue stay unclaimed and a matching opener can still root one.
                continue
        if delivery.is_opener and delivery.alert.throttle_seconds > 0:
            throttled_openers.setdefault(delivery.alert.id, delivery.alert)
        if delivery.is_opener and delivery.thread is None:
            # The throttle window is claimed only for openers that would start a
            # new conversation, once per alert; every destination of the alert
            # shares the claim. An existing unrooted row was authorized by an
            # earlier claim (its root post failed), so rooting it bypasses the
            # window and stays retryable no matter who holds the key now.
            # Replies are never throttled.
            if delivery.alert.id not in throttle_allowed:
                throttle_allowed[delivery.alert.id] = _opener_throttle_allows(delivery.alert, inputs)
            if not throttle_allowed[delivery.alert.id]:
                continue
        try:
            if _deliver_one(delivery, inputs):
                delivered += 1
                if delivery.is_opener:
                    rooted.add(delivery.alert.id)
        except AlertThreadBusyError:
            # Expected contention, not a fault: the retry lands as a reply once the
            # holder has saved its root.
            logger.info(
                "error_tracking_alert_thread_busy",
                team_id=inputs.team_id,
                alert_id=str(delivery.alert.id),
                destination_id=str(delivery.destination.id),
                issue_id=inputs.issue_id,
                notification_id=inputs.notification_id,
            )
            failures += 1
            retrying.add(delivery.alert.id)
        except SlackApiError as error:
            code = _slack_error_code(error)
            _record_delivery_outcome(delivery.destination, error=f"Slack error: {code}")
            if code in SLACK_TERMINAL_ERRORS:
                # A configuration gap, like the missing-integration path: retrying
                # would burn every attempt for the same outcome.
                logger.warning(
                    "error_tracking_alert_destination_rejected",
                    team_id=inputs.team_id,
                    alert_id=str(delivery.alert.id),
                    destination_id=str(delivery.destination.id),
                    slack_error=code,
                )
                continue
            retrying.add(delivery.alert.id)
            if code == "ratelimited":
                retry_after = max(retry_after, _slack_retry_after(error))
            logger.warning(
                "error_tracking_alert_delivery_failed",
                team_id=inputs.team_id,
                alert_id=str(delivery.alert.id),
                destination_id=str(delivery.destination.id),
                slack_error=code,
                notification_id=inputs.notification_id,
            )
            failures += 1
        except Exception:
            # Give every destination a chance before surfacing the failure to
            # Temporal; the per-notification claim makes the retry safe for the
            # deliveries that already went out.
            logger.exception(
                "error_tracking_alert_delivery_failed",
                team_id=inputs.team_id,
                alert_id=str(delivery.alert.id),
                destination_id=str(delivery.destination.id),
                issue_id=inputs.issue_id,
                lifecycle_event=inputs.event,
                notification_id=inputs.notification_id,
            )
            # The exception text can name internal hosts; the log line above keeps it.
            _record_delivery_outcome(delivery.destination, error="Delivery failed unexpectedly")
            failures += 1
            retrying.add(delivery.alert.id)
    for alert_id, alert in throttled_openers.items():
        if alert_id not in rooted and alert_id not in retrying:
            # Every destination of this alert failed for good (or nothing was
            # posted) and no retry is coming: a window that never opened a
            # conversation must not silence the next opener, which is the first
            # one after the user repairs the destination.
            _release_opener_throttle(alert, inputs)
    if failures:
        # Slack's Retry-After drives the next attempt so early retries do not land
        # inside the rate-limit window and burn the budget.
        raise AlertDeliveryError(
            f"{failures} of {len(planned)} alert deliveries failed", retry_after=retry_after or None
        )
    return delivered


def _slack_error_code(error: SlackApiError) -> str:
    try:
        return str(error.response["error"])
    except (KeyError, TypeError):
        return "unknown"


def _slack_retry_after(error: SlackApiError) -> timedelta:
    try:
        return timedelta(seconds=int(error.response.headers.get("Retry-After", 0)))
    except (AttributeError, TypeError, ValueError):
        return timedelta(0)


def _throttle_key(alert: ErrorTrackingAlert, inputs: AlertDeliveryWorkflowInputs) -> str:
    return f"{ALERT_THROTTLE_KEY_PREFIX}:{alert.id}:{inputs.issue_id}"


def _release_opener_throttle(alert: ErrorTrackingAlert, inputs: AlertDeliveryWorkflowInputs) -> None:
    # An earlier attempt of this notification may have rooted a sibling
    # destination; that conversation keeps the window. Older conversations that
    # only got a reply here do not.
    if (
        ErrorTrackingAlertThread.objects.for_team(alert.team_id, canonical=True)
        .filter(alert=alert, issue_id=inputs.issue_id, external_ref__notification_id=inputs.notification_id)
        .exists()
    ):
        return
    try:
        # Compare-and-delete in one step: a stale claimer must never remove a
        # window that a later notification claimed after this key expired.
        get_client().eval(_RELEASE_IF_HELD, 1, _throttle_key(alert, inputs), inputs.notification_id)
    except Exception:
        logger.exception("error_tracking_alert_throttle_release_failed", alert_id=str(alert.id))


def _opener_throttle_allows(alert: ErrorTrackingAlert, inputs: AlertDeliveryWorkflowInputs) -> bool:
    if alert.throttle_seconds <= 0:
        return True
    key = _throttle_key(alert, inputs)
    try:
        client = get_client()
        # The API rejects longer windows; the clamp keeps shared Redis safe from rows
        # that predate that limit.
        ttl = min(alert.throttle_seconds, MAX_THROTTLE_SECONDS)
        if client.set(key, inputs.notification_id, nx=True, ex=ttl):
            return True
        holder = client.get(key)
        allowed = holder is not None and holder.decode() == inputs.notification_id
        if not allowed:
            logger.info(
                "error_tracking_alert_opener_throttled",
                team_id=inputs.team_id,
                alert_id=str(alert.id),
                issue_id=inputs.issue_id,
                notification_id=inputs.notification_id,
            )
        # A retry of the notification that claimed the window must still deliver.
        return allowed
    except Exception:
        # Throttling is noise control: without Redis, deliver rather than drop.
        logger.exception("error_tracking_alert_throttle_check_failed", alert_id=str(alert.id))
        return True


def _record_delivery_outcome(destination: ErrorTrackingAlertDestination, *, error: str | None) -> None:
    now = timezone.now()
    rows = ErrorTrackingAlertDestination.objects.for_team(destination.team_id, canonical=True).filter(id=destination.id)
    try:
        if error is None:
            rows.update(last_delivered_at=now, consecutive_failures=0, updated_at=now)
        else:
            rows.update(
                last_failure_at=now,
                last_error=error[:MAX_RECORDED_ERROR_LENGTH],
                consecutive_failures=F("consecutive_failures") + 1,
                updated_at=now,
            )
    except Exception:
        # The outcome record is observability, never worth failing a delivery over.
        logger.exception("error_tracking_alert_outcome_record_failed", destination_id=str(destination.id))


def _deliver_one(delivery: PlannedDelivery, inputs: AlertDeliveryWorkflowInputs) -> bool:
    thread = delivery.thread
    if thread is None:
        # Planner guarantee: only openers arrive without a thread. The unique
        # constraint dedupes the row; the insert-race loser reuses the winner's.
        try:
            thread, _ = ErrorTrackingAlertThread.objects.for_team(delivery.alert.team_id, canonical=True).get_or_create(
                alert=delivery.alert,
                issue_id=inputs.issue_id,
                destination=delivery.destination,
                defaults={"team_id": delivery.alert.team_id},
            )
        except IntegrityError:
            # The issue row is gone (merged away or deleted): nothing to alert on.
            return False

    client = _slack_client(delivery.destination)
    if client is None:
        # A revoked or repointed integration is a configuration gap, not a
        # transient failure: retries cannot fix it, so skip without raising.
        # Per-destination failure records land in the follow-up outcomes layer.
        logger.warning(
            "error_tracking_alert_destination_unusable",
            team_id=delivery.alert.team_id,
            alert_id=str(delivery.alert.id),
            destination_id=str(delivery.destination.id),
        )
        _record_delivery_outcome(delivery.destination, error="Slack integration is missing or was revoked")
        return False

    claimed_at = _claim_thread(thread, inputs)
    try:
        # Everything below reads row state written by whoever held the claim last.
        thread.refresh_from_db()
        posted = _post_claimed(client, thread, delivery, inputs, claimed_at)
    except SlackApiError as error:
        if _slack_error_code(error) in SLACK_TERMINAL_ERRORS:
            # Nothing to retry for this destination, so the notification counts as
            # handled here: an activity retry for a sibling destination's transient
            # failure must not call Slack for this one again.
            _finalize_thread(thread, inputs, claimed_at)
        else:
            _release_thread(thread, inputs, claimed_at)
        raise
    except Exception:
        # A failed post frees the thread for whoever comes next; this notification's
        # retry then lands wherever the thread is by that time.
        _release_thread(thread, inputs, claimed_at)
        raise
    if not posted:
        _release_thread(thread, inputs, claimed_at)
    return posted


def _post_claimed(
    client: WebClient,
    thread: ErrorTrackingAlertThread,
    delivery: PlannedDelivery,
    inputs: AlertDeliveryWorkflowInputs,
    claimed_at: datetime,
) -> bool:
    if inputs.notification_id in (thread.delivered_notification_ids or []):
        return False

    external_ref = thread.external_ref
    root_headline = thread.root_headline
    if not external_ref.get("ts"):
        if not delivery.is_opener:
            # The row exists but was never rooted (a previous root post failed):
            # leave this notification undelivered so a later opener still roots.
            return False
        channel = delivery.destination.config.get("channel")
        if not channel:
            _record_delivery_outcome(delivery.destination, error="Destination has no Slack channel configured")
            return False
        message = build_root_message(inputs)
        response = client.chat_postMessage(channel=channel, blocks=message["blocks"], text=message["text"])
        # The rooting notification is recorded so a later attempt of it can tell
        # its own root from an older conversation.
        external_ref = {"channel": response["channel"], "ts": response["ts"], "notification_id": inputs.notification_id}
        root_headline = message["headline"]
    else:
        reply = build_reply_text(inputs)
        if reply is None:
            return False
        # Replies stay in the thread's own channel: a provider thread cannot move,
        # so a repointed destination only applies to newly opened threads.
        client.chat_postMessage(channel=external_ref["channel"], thread_ts=external_ref["ts"], text=reply)
        _maybe_edit_root(client, thread, inputs)

    _finalize_thread(thread, inputs, claimed_at, external_ref=external_ref, root_headline=root_headline)
    _record_delivery_outcome(delivery.destination, error=None)
    return True


def _finalize_thread(
    thread: ErrorTrackingAlertThread,
    inputs: AlertDeliveryWorkflowInputs,
    claimed_at: datetime,
    *,
    external_ref: dict | None = None,
    root_headline: str | None = None,
) -> None:
    """Record the notification as handled on the thread and release the claim.

    Fenced on the claim time: a holder that outlived the TTL and was superseded must
    not overwrite the successor's state or clear the successor's claim.
    """
    delivered_ids = [*(thread.delivered_notification_ids or []), inputs.notification_id][
        -DELIVERED_NOTIFICATION_IDS_CAP:
    ]
    finalized = (
        ErrorTrackingAlertThread.objects.for_team(thread.team_id, canonical=True)
        .filter(id=thread.id, pending_notification_id=inputs.notification_id, pending_claimed_at=claimed_at)
        .update(
            external_ref=external_ref if external_ref is not None else thread.external_ref,
            root_headline=root_headline if root_headline is not None else thread.root_headline,
            delivered_notification_ids=delivered_ids,
            pending_notification_id=None,
            pending_claimed_at=None,
            updated_at=timezone.now(),
        )
    )
    if not finalized:
        logger.warning(
            "error_tracking_alert_thread_claim_superseded",
            thread_id=str(thread.id),
            notification_id=inputs.notification_id,
        )


def _claim_thread(thread: ErrorTrackingAlertThread, inputs: AlertDeliveryWorkflowInputs) -> datetime:
    now = timezone.now()
    claimed = (
        ErrorTrackingAlertThread.objects.for_team(thread.team_id, canonical=True)
        .filter(id=thread.id)
        # A live claim is busy for everyone, this notification's own retry included:
        # a timed-out attempt may still be mid-post when Temporal starts the retry.
        # The retry of a holder that crashed waits for the claim to go stale instead.
        .filter(Q(pending_notification_id__isnull=True) | Q(pending_claimed_at__lt=now - PENDING_CLAIM_TTL))
        .update(pending_notification_id=inputs.notification_id, pending_claimed_at=now)
    )
    if not claimed:
        raise AlertThreadBusyError(f"thread {thread.id} is being posted to by another notification")
    return now


def _release_thread(
    thread: ErrorTrackingAlertThread, inputs: AlertDeliveryWorkflowInputs, claimed_at: datetime
) -> None:
    # Fenced like the finalize: a newer attempt of the same notification may have
    # re-claimed, and this attempt must not release on its behalf.
    ErrorTrackingAlertThread.objects.for_team(thread.team_id, canonical=True).filter(
        id=thread.id, pending_notification_id=inputs.notification_id, pending_claimed_at=claimed_at
    ).update(pending_notification_id=None, pending_claimed_at=None)


def _maybe_edit_root(client: WebClient, thread: ErrorTrackingAlertThread, inputs: AlertDeliveryWorkflowInputs) -> None:
    if inputs.event not in ROOT_EDIT_EVENTS:
        return
    message = build_root_edit(inputs, headline=thread.root_headline or DEFAULT_HEADLINE)
    try:
        client.chat_update(
            channel=thread.external_ref["channel"],
            ts=thread.external_ref["ts"],
            blocks=message["blocks"],
            text=message["text"],
        )
    except Exception:
        # The threaded reply already delivered the update; a failed root edit only
        # leaves a stale status line behind, so it never fails the delivery.
        logger.exception(
            "error_tracking_alert_root_edit_failed",
            thread_id=str(thread.id),
            lifecycle_event=inputs.event,
        )


def _slack_client(destination: ErrorTrackingAlertDestination) -> WebClient | None:
    integration = destination.integration
    if integration is None or integration.kind != Integration.IntegrationKind.SLACK:
        return None
    return SlackIntegration(integration).client
