"""`send_message`: a scout asks to message a person or channel through an owner-set route.

The fourth output channel, next to signals, reports and structured output. A report records what a
scout found. A message interrupts a person, so the scout decides whether a finding deserves one and
the config decides who receives it: the scout names a route `key` from `output_destinations.messages`
and never a recipient (see `message_routes.py`).

Nothing is posted during the run. A call saves a `SignalScoutMessage` row as `queued`, and
`message_send.send_queued_scout_messages` sends the run's queued rows when the run ends, after the
report posts, so a message can link to its report and a report edited several times in one run
reaches Slack once. A second call in the same run with the same route and `dedupe_key` replaces the
queued message.

Limits are enforced here, under a lock on the scout's lane: at most `MAX_MESSAGES_PER_SCOUT_PER_WINDOW` per scout
in any rolling `MESSAGE_CAP_WINDOW`, and no message whose route and `dedupe_key` were sent in the last
`DEDUPE_WINDOW`. A refusal is an outcome, not an error, and is recorded on the run's metadata.

The title and body pass the report safety judge before the message is queued. The report a message
points at was judged on its own text, and the scout writes the message text separately, so text the
judge would withhold from a report must not reach a person through a message instead.
"""

from __future__ import annotations

import uuid
import logging

from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

import posthoganalytics
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutMessage, SignalScoutRun
from products.signals.backend.scout_harness.limits import SCOUT_TRIAL_METADATA_KEY
from products.signals.backend.scout_harness.message_routes import (
    DEDUPE_WINDOW,
    MAX_MESSAGE_BODY_LENGTH,
    MAX_MESSAGE_TITLE_LENGTH,
    MAX_MESSAGES_PER_SCOUT_PER_WINDOW,
    MESSAGE_CAP_WINDOW,
    UNSENDABLE_REPORT_STATUSES,
    find_message_route,
    get_message_routes,
    lock_scout_message_lane,
    scout_send_message_enabled,
)
from products.signals.backend.scout_report.judge import judge_edited_report_content

logger = logging.getLogger(__name__)

MAX_DEDUPE_KEY_LENGTH = 200
MAX_RECENT_DEDUPE_KEYS = 10
# `SignalScoutRun.metadata` key holding the refused calls of the run, newest last.
MESSAGE_REFUSALS_METADATA_KEY = "message_refusals"
MAX_RECORDED_REFUSALS = 20


class SendMessageOutcome(models.TextChoices):
    QUEUED = "queued"
    REPLACED = "replaced"
    DUPLICATE = "duplicate"
    OVER_CAP = "over_cap"
    DRY_RUN = "dry_run"


class InvalidMessageError(ValueError):
    """The call cannot be accepted as sent: the feature is off, the route is unknown, the report is
    not this run's, the safety judge rejected the text, or a field is malformed. The scout can fix
    the call and retry."""


@frozen
class SendMessageResult:
    outcome: SendMessageOutcome
    message_id: str | None
    # Set on `duplicate` only: the keys recently sent on this route, so the scout sees the convention.
    recent_dedupe_keys: tuple[str, ...] = ()


def send_message_sync(
    *,
    team: Team,
    run: SignalScoutRun,
    route_key: str,
    report_id: str | None,
    title: str,
    body: str,
    dedupe_key: str,
) -> SendMessageResult:
    if team.id != run.team_id:
        raise RuntimeError(f"send_message: team {team.id} does not own run {run.id} (team {run.team_id})")
    title = " ".join(title.split())
    body = body.strip()
    dedupe_key = dedupe_key.strip()
    _validate_fields(title=title, body=body, dedupe_key=dedupe_key)
    if (run.metadata or {}).get(SCOUT_TRIAL_METADATA_KEY):
        raise InvalidMessageError("A private trial run cannot send messages.")
    config = SignalScoutConfig.all_teams.filter(pk=run.scout_config_id).first() if run.scout_config_id else None
    routes = get_message_routes(config.output_destinations) if config else ()
    if not routes or not scout_send_message_enabled(team):
        raise InvalidMessageError("This scout has no message routes, so it cannot send messages.")
    if find_message_route(config.output_destinations if config else None, route_key) is None:
        known = ", ".join(f"`{route.key}`" for route in routes)
        raise InvalidMessageError(f"Unknown route `{route_key}`. This scout's routes are: {known}.")

    dry_run = config is not None and not config.emit
    report = None if dry_run else _resolve_report(team=team, run=run, report_id=report_id)
    # Outside the queue transaction: the judge is a model call and must not hold the lane lock.
    safety = async_to_sync(judge_edited_report_content)(team_id=team.id, title=title, summary=body)
    if not safety.choice:
        raise InvalidMessageError(f"Message rejected by the safety judge: {safety.explanation}")

    result = _queue(
        team=team,
        run=run,
        route_key=route_key,
        report=report,
        title=title,
        body=body,
        dedupe_key=dedupe_key,
        dry_run=dry_run,
    )
    _capture_requested(team=team, run=run, route_key=route_key, outcome=result.outcome)
    return result


def _validate_fields(*, title: str, body: str, dedupe_key: str) -> None:
    if not title:
        raise InvalidMessageError("`title` must not be empty.")
    if len(title) > MAX_MESSAGE_TITLE_LENGTH:
        raise InvalidMessageError(f"`title` is {len(title)} characters; the limit is {MAX_MESSAGE_TITLE_LENGTH}.")
    if not body:
        raise InvalidMessageError("`body` must not be empty.")
    if len(body) > MAX_MESSAGE_BODY_LENGTH:
        raise InvalidMessageError(f"`body` is {len(body)} characters; the limit is {MAX_MESSAGE_BODY_LENGTH}.")
    if not dedupe_key or len(dedupe_key) > MAX_DEDUPE_KEY_LENGTH:
        raise InvalidMessageError(f"`dedupe_key` must be 1 to {MAX_DEDUPE_KEY_LENGTH} characters.")


def _resolve_report(*, team: Team, run: SignalScoutRun, report_id: str | None) -> SignalReport:
    if not report_id:
        raise InvalidMessageError(
            "`report_id` is required. Write or edit the report this message is about first, then send."
        )
    try:
        report_uuid = uuid.UUID(str(report_id))
    except ValueError:
        raise InvalidMessageError(f"`report_id` {report_id!r} is not a report id.")
    report = SignalReport.objects.filter(team_id=team.id, id=report_uuid).first()
    if report is None:
        raise InvalidMessageError(f"No report {report_id} exists in this project.")
    if report.status in UNSENDABLE_REPORT_STATUSES:
        # A report the safety judge suppressed is still stored and still on the run, so without this a
        # scout could send the content the judge withheld from every other channel.
        raise InvalidMessageError(f"Report {report_id} is not shown in the inbox, so no message can point at it.")
    touched = (
        SignalScoutRun.all_teams.filter(pk=run.pk)
        .filter(Q(emitted_report_ids__contains=[str(report_uuid)]) | Q(edited_report_ids__contains=[str(report_uuid)]))
        .exists()
    )
    if not touched:
        raise InvalidMessageError(
            f"Report {report_id} was not written or edited by this run. A message must point at a report this "
            "run wrote or edited: write or edit it first, then send."
        )
    return report


def _queue(
    *,
    team: Team,
    run: SignalScoutRun,
    route_key: str,
    report: SignalReport | None,
    title: str,
    body: str,
    dedupe_key: str,
    dry_run: bool,
) -> SendMessageResult:
    now = timezone.now()
    pending_status = SignalScoutMessage.Status.DRY_RUN if dry_run else SignalScoutMessage.Status.QUEUED
    with transaction.atomic():
        # The cap and the dedupe window cover every run of the scout, and runs of one scout can overlap,
        # so the lane is locked rather than the run. The config row is no lane: it can be recreated.
        lock_scout_message_lane(team_id=team.id, skill_name=run.skill_name)
        locked_run = SignalScoutRun.all_teams.select_for_update(of=("self",)).filter(pk=run.pk).first()
        if locked_run is None:
            raise InvalidMessageError("The run row is gone; nothing was queued.")
        existing = SignalScoutMessage.all_teams.filter(
            team_id=team.id, run_id=run.pk, route_key=route_key, dedupe_key=dedupe_key
        ).first()
        if existing is not None:
            # The status is rewritten too: the owner can flip `emit` during the run, and the row must
            # follow the run's current mode rather than collide with the unique constraint.
            existing.report = report
            existing.title = title
            existing.body = body
            existing.status = pending_status
            existing.save(update_fields=["report", "title", "body", "status", "updated_at"])
            return SendMessageResult(outcome=SendMessageOutcome.REPLACED, message_id=str(existing.id))

        lane = SignalScoutMessage.all_teams.filter(team_id=team.id, skill_name=run.skill_name)
        # Another run's queued message counts as sent: it goes out when that run ends.
        on_route = lane.filter(route_key=route_key).filter(
            Q(status=SignalScoutMessage.Status.SENT, sent_at__gte=now - DEDUPE_WINDOW)
            | Q(status=SignalScoutMessage.Status.QUEUED, created_at__gte=now - MESSAGE_CAP_WINDOW)
        )
        if on_route.filter(dedupe_key=dedupe_key).exists():
            recent_keys = tuple(
                dict.fromkeys(on_route.order_by("-created_at").values_list("dedupe_key", flat=True)[:50])
            )[:MAX_RECENT_DEDUPE_KEYS]
            _record_refusal(locked_run, SendMessageOutcome.DUPLICATE, route_key, dedupe_key, now)
            return SendMessageResult(
                outcome=SendMessageOutcome.DUPLICATE, message_id=None, recent_dedupe_keys=recent_keys
            )

        # Queued rows count wherever they came from: a reaped run's queued messages are still sent. Only
        # inside the window, so a row a failed send left queued stops counting once the window passes.
        spent = lane.filter(
            Q(status=SignalScoutMessage.Status.SENT, sent_at__gte=now - MESSAGE_CAP_WINDOW)
            | Q(status=SignalScoutMessage.Status.QUEUED, created_at__gte=now - MESSAGE_CAP_WINDOW)
            | Q(status=SignalScoutMessage.Status.DRY_RUN, run_id=run.pk)
        ).count()
        if spent >= MAX_MESSAGES_PER_SCOUT_PER_WINDOW:
            _record_refusal(locked_run, SendMessageOutcome.OVER_CAP, route_key, dedupe_key, now)
            return SendMessageResult(outcome=SendMessageOutcome.OVER_CAP, message_id=None)

        message = SignalScoutMessage.all_teams.create(
            team_id=team.id,
            run_id=run.pk,
            skill_name=run.skill_name,
            report=report,
            route_key=route_key,
            dedupe_key=dedupe_key,
            title=title,
            body=body,
            status=pending_status,
        )
    outcome = SendMessageOutcome.DRY_RUN if dry_run else SendMessageOutcome.QUEUED
    return SendMessageResult(outcome=outcome, message_id=str(message.id))


def _record_refusal(
    locked_run: SignalScoutRun, outcome: SendMessageOutcome, route_key: str, dedupe_key: str, now
) -> None:
    metadata = dict(locked_run.metadata or {})
    refusals = metadata.get(MESSAGE_REFUSALS_METADATA_KEY)
    refusals = list(refusals) if isinstance(refusals, list) else []
    refusals.append({"outcome": str(outcome), "route_key": route_key, "dedupe_key": dedupe_key, "at": now.isoformat()})
    metadata[MESSAGE_REFUSALS_METADATA_KEY] = refusals[-MAX_RECORDED_REFUSALS:]
    locked_run.metadata = metadata
    locked_run.save(update_fields=["metadata"])


def _capture_requested(*, team: Team, run: SignalScoutRun, route_key: str, outcome: SendMessageOutcome) -> None:
    try:
        posthoganalytics.capture(
            event="signals_scout_message_requested",
            distinct_id=str(team.uuid),
            properties={
                "skill_name": run.skill_name,
                "scout_config_id": str(run.scout_config_id) if run.scout_config_id else None,
                "run_id": str(run.id),
                "route_key": route_key,
                "outcome": str(outcome),
            },
            groups=groups(team.organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture message analytics event",
            extra={"team_id": team.id, "run_id": str(run.id)},
        )
