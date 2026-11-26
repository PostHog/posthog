"""Send a scout run's queued messages when the run ends.

Called from every terminal path of a run: success, failure and cancellation in `runner.py`, and a
run reaped by `_self_heal_stale_runs` after a worker or sandbox loss. Queued messages are sent in all
four because the report each one points at already exists. The send runs after the run's report
deliveries were enqueued, so a message can link to a report Slack already shows.

Each queued row is claimed with a compare-and-set on its status, so two terminal paths that reach the
same run (a cancelled activity and a later reap) cannot send one message twice. Before sending, the
feature flag and the route are read again from the live config: a route removed during the run is
not sent to.
"""

from __future__ import annotations

import uuid
import logging
from functools import partial
from typing import Any

from django.db import transaction
from django.utils import timezone

from posthog.api.capture import capture_batch_internal
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.signals.backend.models import (
    SignalScoutConfig,
    SignalScoutMessage,
    SignalScoutMessageDelivery,
    SignalScoutRun,
)
from products.signals.backend.scout_harness.message_routes import (
    MESSAGE_TARGET_SLACK_DM,
    MessageRoute,
    find_message_route,
    scout_send_message_enabled,
)
from products.signals.backend.tasks import enqueue_scout_slack_delivery

logger = logging.getLogger(__name__)

CUSTOMER_MESSAGE_EVENT = "$scout_message"
_MESSAGE_EVENT_SOURCE = "signals_scout_message"


def send_queued_scout_messages(*, team_id: int, run_id: uuid.UUID | str) -> int:
    """Send this run's queued messages and return how many were accepted for sending."""
    if not SignalScoutMessage.all_teams.filter(
        team_id=team_id, run_id=run_id, status=SignalScoutMessage.Status.QUEUED
    ).exists():
        return 0
    run = SignalScoutRun.all_teams.select_related("team", "scout_config").filter(team_id=team_id, pk=run_id).first()
    if run is None:
        return 0
    team = run.team
    config = run.scout_config
    enabled = scout_send_message_enabled(team)
    integration_id = _integration_id(config)
    sent = 0
    for message_id in SignalScoutMessage.all_teams.filter(
        team_id=team_id, run_id=run_id, status=SignalScoutMessage.Status.QUEUED
    ).values_list("id", flat=True):
        try:
            if _send_one(
                team=team,
                run=run,
                message_id=message_id,
                config=config,
                enabled=enabled,
                integration_id=integration_id,
            ):
                sent += 1
        except Exception as exc:
            capture_exception(exc, {"team_id": team_id, "run_id": str(run_id), "message_id": str(message_id)})
            logger.exception(
                "signals_scout.message_send_failed",
                extra={"team_id": team_id, "run_id": str(run_id), "message_id": str(message_id)},
            )
    return sent


def send_queued_scout_messages_safely(*, team_id: int, run_id: uuid.UUID | str) -> None:
    """The runner's entry point: a failed send must never change how the run ends."""
    try:
        send_queued_scout_messages(team_id=team_id, run_id=run_id)
    except Exception as exc:
        capture_exception(exc, {"team_id": team_id, "run_id": str(run_id)})
        logger.exception("signals_scout.message_send_failed", extra={"team_id": team_id, "run_id": str(run_id)})


def _integration_id(config: SignalScoutConfig | None) -> int | None:
    slack = (config.output_destinations or {}).get("slack") if config else None
    integration_id = slack.get("integration_id") if isinstance(slack, dict) else None
    if isinstance(integration_id, int) and not isinstance(integration_id, bool) and integration_id > 0:
        return integration_id
    return None


def _send_one(
    *,
    team: Team,
    run: SignalScoutRun,
    message_id: Any,
    config: SignalScoutConfig | None,
    enabled: bool,
    integration_id: int | None,
) -> bool:
    with transaction.atomic():
        message = (
            SignalScoutMessage.all_teams.select_for_update()
            .filter(pk=message_id, status=SignalScoutMessage.Status.QUEUED)
            .first()
        )
        if message is None:
            return False
        route = find_message_route(config.output_destinations, message.route_key) if config else None
        drop_reason = _drop_reason(message=message, route=route, enabled=enabled, integration_id=integration_id)
        if drop_reason is not None or route is None or integration_id is None:
            message.status = SignalScoutMessage.Status.DROPPED
            message.drop_reason = drop_reason or SignalScoutMessage.DropReason.ROUTE_REMOVED
            message.save(update_fields=["status", "drop_reason", "updated_at"])
            logger.info(
                "signals_scout.message_dropped",
                extra={"team_id": team.id, "run_id": str(run.id), "reason": message.drop_reason},
            )
            return False
        message.status = SignalScoutMessage.Status.SENT
        message.sent_at = timezone.now()
        message.save(update_fields=["status", "sent_at", "updated_at"])
        deliveries = _create_deliveries(message=message, route=route, integration_id=integration_id)
        for delivery in deliveries:
            transaction.on_commit(
                partial(
                    enqueue_scout_slack_delivery,
                    team_id=team.id,
                    output_type="message",
                    output_id=str(delivery.id),
                    run_id=str(run.id),
                    delivery_id=str(delivery.id),
                    integration_id=integration_id,
                    channel=delivery.target_id,
                ),
                robust=True,
            )
        transaction.on_commit(
            partial(_capture_message_event, team=team, run=run, message=message, target_count=len(deliveries)),
            robust=True,
        )
    return True


def _drop_reason(
    *, message: SignalScoutMessage, route: MessageRoute | None, enabled: bool, integration_id: int | None
) -> SignalScoutMessage.DropReason | None:
    if not enabled:
        return SignalScoutMessage.DropReason.FLAG_OFF
    if route is None:
        return SignalScoutMessage.DropReason.ROUTE_REMOVED
    if integration_id is None:
        return SignalScoutMessage.DropReason.NO_SLACK_INTEGRATION
    if message.report_id is None:
        return SignalScoutMessage.DropReason.REPORT_MISSING
    return None


def _create_deliveries(
    *, message: SignalScoutMessage, route: MessageRoute, integration_id: int
) -> list[SignalScoutMessageDelivery]:
    # Two targets that resolve to one Slack id (the same member listed twice, or `U1|@a` and `U1`) get one post.
    unique_targets = {target.target_id: target for target in route.targets}
    return [
        SignalScoutMessageDelivery.all_teams.create(
            team_id=message.team_id,
            message=message,
            target_type=(
                SignalScoutMessageDelivery.TargetType.SLACK_DM
                if target.type == MESSAGE_TARGET_SLACK_DM
                else SignalScoutMessageDelivery.TargetType.SLACK_CHANNEL
            ),
            target_id=target.target_id,
            integration_id=integration_id,
        )
        for target in unique_targets.values()
    ]


def _capture_message_event(*, team: Team, run: SignalScoutRun, message: SignalScoutMessage, target_count: int) -> None:
    """One `$scout_message` event per message, not per target, in the team's own project, so a workflow
    can trigger on it. The message id is the event uuid, so a retried capture collapses at ingestion."""
    try:
        capture_batch_internal(
            events=[
                {
                    "event": CUSTOMER_MESSAGE_EVENT,
                    "distinct_id": f"signals_scout:{run.skill_name}",
                    "event_uuid": str(message.id),
                    "timestamp": (message.sent_at or timezone.now()).isoformat(),
                    "properties": {
                        "skill_name": run.skill_name,
                        "run_id": str(run.id),
                        "task_run_id": str(run.task_run_id) if run.task_run_id else None,
                        "message_id": str(message.id),
                        "route_key": message.route_key,
                        "dedupe_key": message.dedupe_key,
                        "report_id": str(message.report_id) if message.report_id else None,
                        "title": message.title,
                        "body": message.body,
                        "target_count": target_count,
                    },
                }
            ],
            token=team.api_token,
            event_source=_MESSAGE_EVENT_SOURCE,
            process_person_profile=False,
        ).raise_for_status()
    except Exception:
        logger.warning(
            "signals_scout: failed to capture $scout_message event",
            extra={"team_id": team.id, "run_id": str(run.id), "message_id": str(message.id)},
        )
