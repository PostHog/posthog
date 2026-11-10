"""The daily work focus: the onboarding work focus again, every workday at a time the person picks, in their Slack
timezone. A sweep every 30 minutes starts a run for each person whose time has come, so a run starts up to 30
minutes after the picked time."""

import json
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.models import SlackDailyFocus, SlackUserProfileCache
from products.slack_app.backend.services.slack_messages import context_block
from products.slack_app.backend.services.slack_user_info import get_slack_user_info
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

DEFAULT_DAILY_FOCUS_TIME = time(9, 0)
# The onboarding prefix routes the click to the region that owns the install.
# pinned: Slack action id on DMs that people already have
DAILY_FOCUS_OFF_ACTION_ID = "slack_onboarding:daily_focus_off"
DAILY_FOCUS_FOOTER_BLOCK_ID = "daily_focus_footer"
# A sweep that finds more people than this leaves the rest for the next sweep, 30 minutes later.
SWEEP_BATCH_SIZE = 1000
# pinned: analytics event names, renaming breaks dashboards
TURNED_ON_EVENT = "slack app daily work focus turned on"
TURNED_OFF_EVENT = "slack app daily work focus turned off"
TIME_CHANGED_EVENT = "slack app daily work focus time changed"


@frozen
class DailyFocusSettings:
    # None means the person never chose.
    enabled: bool | None
    at: time


@frozen
class DueDailyFocus:
    integration_id: int
    slack_team_id: str
    slack_user_id: str
    # The previous run time, as epoch seconds. The run reads the messages sent after it.
    since: int


def zone_named(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def next_run_after(moment: datetime, zone: ZoneInfo, at: time) -> datetime:
    """The first workday (Monday to Friday) at ``at`` in ``zone`` that comes after ``moment``."""
    day = moment.astimezone(zone).date()
    while True:
        candidate = datetime.combine(day, at, tzinfo=zone)
        if day.weekday() < 5 and candidate > moment:
            return candidate.astimezone(UTC)
        day += timedelta(days=1)


def previous_run_before(scheduled: datetime, zone: ZoneInfo, at: time) -> datetime:
    """The workday run before ``scheduled``. A Monday run reads back to Friday's."""
    day = scheduled.astimezone(zone).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC)


def person_zone(integration: WorkspaceIntegration, slack_user_id: str) -> ZoneInfo:
    """Refreshes the cached Slack profile when it is old, so a person who travels gets their new timezone."""
    try:
        user = get_slack_user_info(SlackIntegration(integration), integration, slack_user_id).get("user") or {}
    except Exception:
        logger.warning("slack_app_daily_focus_timezone_failed", integration_id=integration.id, exc_info=True)
        user = {}
    return zone_named(user.get("tz") if isinstance(user, dict) else None)


def cached_zone(integration_id: int, slack_user_id: str) -> ZoneInfo | None:
    """The timezone from the cached Slack profile, without a Slack call. None when the cache has none."""
    name = (
        SlackUserProfileCache.objects.filter(integration_id=integration_id, slack_user_id=slack_user_id)
        .values_list("tz", flat=True)
        .first()
    )
    return zone_named(name) if name else None


def parse_clock(value: object) -> time | None:
    """A time from Slack's timepicker, which sends "HH:mm"."""
    try:
        return time.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def resolve_daily_focus(slack_workspace_id: str, slack_user_id: str) -> DailyFocusSettings:
    row = SlackDailyFocus.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id).first()
    if row is None:
        return DailyFocusSettings(enabled=None, at=DEFAULT_DAILY_FOCUS_TIME)
    return DailyFocusSettings(enabled=row.next_run_at is not None, at=row.at)


def _locked_row(integration: WorkspaceIntegration, slack_user_id: str) -> SlackDailyFocus:
    row, _ = SlackDailyFocus.objects.select_for_update().get_or_create(
        slack_workspace_id=integration.integration_id,
        slack_user_id=slack_user_id,
        defaults={"integration_id": integration.id, "at": DEFAULT_DAILY_FOCUS_TIME},
    )
    return row


def turn_on_daily_focus(integration: WorkspaceIntegration, slack_user_id: str, *, source: str) -> None:
    zone = person_zone(integration, slack_user_id)
    with transaction.atomic():
        row = _locked_row(integration, slack_user_id)
        row.integration_id = integration.id
        row.next_run_at = next_run_after(timezone.now(), zone, row.at)
        row.save(update_fields=["integration_id", "next_run_at", "updated_at"])
    capture_slack_event(integration, TURNED_ON_EVENT, slack_user_id=slack_user_id, source=source)


def turn_off_daily_focus(integration: WorkspaceIntegration, slack_user_id: str, *, source: str) -> None:
    with transaction.atomic():
        row = _locked_row(integration, slack_user_id)
        row.next_run_at = None
        row.save(update_fields=["next_run_at", "updated_at"])
    capture_slack_event(integration, TURNED_OFF_EVENT, slack_user_id=slack_user_id, source=source)


def set_daily_focus_time(integration: WorkspaceIntegration, slack_user_id: str, at: time) -> None:
    """Keeps the daily work focus on or off. When it is on, the next run moves to the new time."""
    zone = person_zone(integration, slack_user_id)
    with transaction.atomic():
        row = _locked_row(integration, slack_user_id)
        row.at = at
        if row.next_run_at is not None:
            row.next_run_at = next_run_after(timezone.now(), zone, at)
        row.save(update_fields=["at", "next_run_at", "updated_at"])
    capture_slack_event(integration, TIME_CHANGED_EVENT, slack_user_id=slack_user_id, at=at.strftime("%H:%M"))


def claim_due_daily_focus(now: datetime, *, limit: int = SWEEP_BATCH_SIZE) -> list[DueDailyFocus]:
    """Moves each due person to their next workday before their run starts, so a sweep that runs twice never sends
    a day twice. A run that then fails to start is skipped for that day, not sent twice."""
    with transaction.atomic():
        rows = list(
            SlackDailyFocus.objects.select_for_update(skip_locked=True)
            .filter(next_run_at__lte=now)
            .order_by("next_run_at")[:limit]
        )
        zones = {
            (profile["integration_id"], profile["slack_user_id"]): profile["tz"]
            for profile in SlackUserProfileCache.objects.filter(
                integration_id__in={row.integration_id for row in rows},
                slack_user_id__in={row.slack_user_id for row in rows},
            ).values("integration_id", "slack_user_id", "tz")
        }
        due = []
        for row in rows:
            scheduled = row.next_run_at
            if scheduled is None:
                continue
            zone = zone_named(zones.get((row.integration_id, row.slack_user_id)))
            row.next_run_at = next_run_after(now, zone, row.at)
            due.append(
                DueDailyFocus(
                    integration_id=row.integration_id,
                    slack_team_id=row.slack_workspace_id,
                    slack_user_id=row.slack_user_id,
                    since=int(previous_run_before(scheduled, zone, row.at).timestamp()),
                )
            )
        SlackDailyFocus.objects.bulk_update(rows, ["next_run_at"])
    return due


def _clock(at: time) -> str:
    return at.strftime("%H:%M")


def daily_focus_footer_block(integration: WorkspaceIntegration, at: time, zone: ZoneInfo, *, first: bool) -> dict:
    text = (
        f"📅 I'll send you this every workday at {_clock(at)} ({zone.key})."
        if first
        else f"📅 Every workday at {_clock(at)} ({zone.key})"
    )
    return {
        "type": "section",
        "block_id": DAILY_FOCUS_FOOTER_BLOCK_ID,
        "text": {"type": "mrkdwn", "text": text},
        "accessory": {
            "type": "button",
            "text": {"type": "plain_text", "text": "Turn off"},
            "action_id": DAILY_FOCUS_OFF_ACTION_ID,
            "value": json.dumps({"integration_id": integration.id}, separators=(",", ":")),
        },
    }


def daily_focus_off_blocks(blocks: list[dict]) -> list[dict]:
    """The DM's blocks with the footer saying the daily work focus is off, and no button to turn it off again."""
    off = {
        **context_block("📅 Your daily work focus is off. You can turn it back on in the Home tab."),
        "block_id": DAILY_FOCUS_FOOTER_BLOCK_ID,
    }
    return [off if block.get("block_id") == DAILY_FOCUS_FOOTER_BLOCK_ID else block for block in blocks]


def read_off_click(payload: dict[str, Any]) -> int | None:
    """The integration id behind a Turn off click."""
    for action in payload.get("actions") or []:
        if action.get("action_id") != DAILY_FOCUS_OFF_ACTION_ID:
            continue
        try:
            value = json.loads(action.get("value") or "")
        except json.JSONDecodeError:
            return None
        integration_id = value.get("integration_id") if isinstance(value, dict) else None
        return integration_id if isinstance(integration_id, int) else None
    return None
