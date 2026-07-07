import time
from itertools import batched
from typing import cast
from uuid import UUID

from django.db import close_old_connections

import structlog
import posthoganalytics
from temporalio import activity

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.user_permissions import UserPermissions

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.web_analytics.backend.temporal.digest_common import paginate_index, paginate_keyset
from products.web_analytics.backend.temporal.digest_notification.types import (
    DigestBatchInput,
    DigestBatchResult,
    NotificationDigestOutcome,
    OrgBatchPageInput,
    OrgBatchPageResult,
    OrgDigestNotificationCounts,
    SendTestDigestNotificationInput,
)
from products.web_analytics.backend.weekly_digest import build_team_digest

logger = structlog.get_logger(__name__)


def _org_has_realtime_notifications(org: Organization) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                "real-time-notifications",
                str(org.id),
                groups={"organization": str(org.id)},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        logger.warning(
            "wa digest notification: real-time-notifications flag eval failed, treating org as disabled",
            org_id=str(org.id),
            error=str(e),
        )
        capture_exception(e, {"org_id": str(org.id)})
        return False


def _get_digest_variant(user: User, org_id: str, flag_key: str) -> str | None:
    try:
        variant = cast(
            "bool | str | None",
            posthoganalytics.get_feature_flag(
                flag_key,
                distinct_id=str(user.distinct_id),
                groups={"organization": org_id},
                only_evaluate_locally=False,
                send_feature_flag_events=True,
            ),
        )
    except Exception as e:
        logger.warning(
            "wa digest notification: holdout flag eval failed, treating user as not exposed",
            user_id=str(user.uuid),
            org_id=org_id,
            error=str(e),
        )
        capture_exception(e, {"user_id": str(user.uuid), "org_id": org_id})
        return None

    if variant is None:
        return None
    if isinstance(variant, bool):
        return "test" if variant else "control"
    return variant


def _build_title(digest: dict) -> str:
    visitors = int(digest["visitors"]["current"] or 0)
    title = f"{visitors:,} visitor{'' if visitors == 1 else 's'} this week"
    change = digest.get("visitors", {}).get("change")
    if isinstance(change, dict):
        direction = change.get("direction")
        percent = change.get("percent")
        if direction in ("Up", "Down") and percent:
            arrow = "↑" if direction == "Up" else "↓"
            title = f"{title} {arrow}{percent}%"
    return title


def _build_body(digest: dict) -> str:
    pageviews = int(digest["pageviews"]["current"] or 0)
    body = f"{pageviews:,} page view{'' if pageviews == 1 else 's'}"

    top_pages = digest.get("top_pages") or []
    if top_pages and top_pages[0].get("path"):
        body = f"{body} · Top page {top_pages[0]['path']}"

    top_sources = digest.get("top_sources") or []
    if top_sources and top_sources[0].get("name"):
        body = f"{body} · Top source {top_sources[0]['name']}"

    return body


_DIGEST_GOOD_COLOR = "#2f7d4f"


def _digest_change(change: dict | None) -> dict | None:
    if not isinstance(change, dict):
        return None
    direction = change.get("direction")
    percent = change.get("percent")
    if direction not in ("Up", "Down") or not percent:
        return None
    return {"percent": percent, "direction": direction, "is_good": change.get("color") == _DIGEST_GOOD_COLOR}


def _digest_metric(key: str, label: str, value: str, change: dict | None) -> dict:
    return {"key": key, "label": label, "value": value, "change": _digest_change(change)}


def _build_digest_metadata(digest: dict) -> dict:
    team = digest["team"]
    visitors = int(digest["visitors"]["current"] or 0)
    pageviews = int(digest["pageviews"]["current"] or 0)
    sessions = int(digest["sessions"]["current"] or 0)
    bounce = digest["bounce_rate"]["current"] or 0
    return {
        "period_label": "Last 7 days",
        "project_name": team.name,
        "dashboard_url": digest["dashboard_url"],
        "metrics": [
            _digest_metric("visitors", "Visitors", f"{visitors:,}", digest["visitors"]["change"]),
            _digest_metric("pageviews", "Page views", f"{pageviews:,}", digest["pageviews"]["change"]),
            _digest_metric("sessions", "Sessions", f"{sessions:,}", digest["sessions"]["change"]),
            _digest_metric("bounce_rate", "Bounce rate", f"{round(bounce)}%", digest["bounce_rate"]["change"]),
            _digest_metric(
                "avg_session_duration",
                "Avg. session",
                digest["avg_session_duration"]["current"] or "0s",
                digest["avg_session_duration"]["change"],
            ),
        ],
        "top_pages": [
            {"label": p.get("path") or "/", "value": f"{int(p.get('visitors') or 0):,}"}
            for p in (digest.get("top_pages") or [])[:3]
        ],
        "top_sources": [
            {"label": s.get("name") or "", "value": f"{int(s.get('visitors') or 0):,}"}
            for s in (digest.get("top_sources") or [])[:3]
        ],
    }


def _capture_digest_sent(
    user: User,
    org: Organization,
    team_id: int,
    digest: dict,
    variant: str | None,
    notification_id: UUID,
) -> None:
    try:
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(user.distinct_id),
                event="web_analytics_digest_notification_sent",
                properties={
                    "org_id": str(org.id),
                    "team_id": team_id,
                    "variant": variant,
                    "visitors": digest["visitors"]["current"],
                    "pageviews": digest["pageviews"]["current"],
                    "notification_id": str(notification_id),
                },
                groups={"organization": str(org.id)},
            )
    except Exception as e:
        logger.warning(
            "wa digest notification: failed to capture sent event",
            org_id=str(org.id),
            user_id=str(user.uuid),
            error=str(e),
        )
        capture_exception(e, {"org_id": str(org.id), "user_id": str(user.uuid)})


def _accessible_team_data(
    user: User,
    org: Organization,
    membership: OrganizationMembership,
    team_digest_data: dict[int, dict],
) -> dict[int, dict]:
    user_perms = UserPermissions(user)
    accessible: dict[int, dict] = {}
    for team_id, data in team_digest_data.items():
        team = data["team"]
        if user_perms.team(team).effective_membership_level_for_parent_membership(org, membership) is not None:
            accessible[team_id] = data
    return accessible


def _send_digest_notification(
    *,
    user: User,
    org: Organization,
    team_digest_data: dict[int, dict],
    variant: str | None,
) -> NotificationDigestOutcome:
    busiest_team_id = max(team_digest_data, key=lambda tid: team_digest_data[tid]["visitors"]["current"] or 0)
    busiest = team_digest_data[busiest_team_id]

    event = create_notification(
        NotificationData(
            team_id=busiest_team_id,
            notification_type=NotificationType.WEB_ANALYTICS_DIGEST,
            title=_build_title(busiest),
            body=_build_body(busiest),
            target_type=TargetType.USER,
            target_id=str(user.id),
            resource_type="web_analytics",
            priority=Priority.NORMAL,
            source_url=f"/project/{busiest_team_id}/web?utm_source=web_analytics_digest&utm_medium=in_app",
            metadata=_build_digest_metadata(busiest),
        )
    )

    if event is None:
        return NotificationDigestOutcome.SKIPPED_NO_DATA

    _capture_digest_sent(user, org, busiest_team_id, busiest, variant, event.id)
    return NotificationDigestOutcome.SENT


def _expose_and_notify_user(
    *,
    user: User,
    org: Organization,
    membership: OrganizationMembership,
    team_digest_data: dict[int, dict],
    flag_key: str,
    dry_run: bool,
) -> NotificationDigestOutcome:
    accessible = _accessible_team_data(user, org, membership, team_digest_data)
    if not accessible:
        return NotificationDigestOutcome.SKIPPED_NO_DATA

    variant = _get_digest_variant(user, str(org.id), flag_key)
    if variant != "test":
        return NotificationDigestOutcome.CONTROL

    if dry_run:
        return NotificationDigestOutcome.DRY_RUN

    return _send_digest_notification(user=user, org=org, team_digest_data=accessible, variant=variant)


def _build_team_digest_data(org: Organization) -> tuple[dict[int, dict], int, float]:
    build_start = time.monotonic()
    team_digest_data: dict[int, dict] = {}
    for team in Team.objects.filter(organization_id=org.id):
        digest = build_team_digest(team)
        if (digest["visitors"]["current"] or 0) > 0:
            team_digest_data[team.id] = digest
    build_duration = time.monotonic() - build_start
    return team_digest_data, len(team_digest_data), build_duration


def _build_and_send_for_org(org_id: str, flag_key: str, dry_run: bool = False) -> OrgDigestNotificationCounts:
    close_old_connections()

    counts = OrgDigestNotificationCounts()

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning("Organization not found for WA digest notification", org_id=org_id)
        counts.skipped_reason = "org_not_found"
        return counts

    if not _org_has_realtime_notifications(org):
        counts.skipped_reason = "notifications_not_enabled"
        return counts

    if not Team.objects.filter(organization_id=org.id).exists():
        counts.skipped_reason = "no_teams"
        return counts

    team_digest_data, counts.team_count, counts.build_duration = _build_team_digest_data(org)
    if not team_digest_data:
        counts.skipped_reason = "no_wa_data"
        return counts

    send_start = time.monotonic()
    for membership in OrganizationMembership.objects.prefetch_related("user").filter(
        organization_id=org.id, user__is_active=True
    ):
        try:
            outcome = _expose_and_notify_user(
                user=membership.user,
                org=org,
                membership=membership,
                team_digest_data=team_digest_data,
                flag_key=flag_key,
                dry_run=dry_run,
            )
        except Exception as e:
            logger.warning(
                "wa digest notification: failed to process user",
                org_id=org_id,
                user_id=str(membership.user.uuid),
                error=str(e),
            )
            capture_exception(e, {"org_id": org_id, "user_id": str(membership.user.uuid)})
            counts.failed += 1
            continue
        if outcome in (NotificationDigestOutcome.SENT, NotificationDigestOutcome.DRY_RUN):
            counts.sent += 1
        elif outcome == NotificationDigestOutcome.CONTROL:
            counts.control += 1
        elif outcome == NotificationDigestOutcome.SKIPPED_NO_DATA:
            counts.skipped_no_data += 1
        elif outcome == NotificationDigestOutcome.FAILED:
            counts.failed += 1
    counts.send_duration = time.monotonic() - send_start

    logger.info(
        "Sent WA digest notifications for org",
        org_id=org_id,
        sent_count=counts.sent,
        control=counts.control,
        skipped_no_data=counts.skipped_no_data,
        failed=counts.failed,
        team_count=counts.team_count,
    )
    return counts


def _run_wa_digest_notification_batch(input: DigestBatchInput) -> DigestBatchResult:
    close_old_connections()

    tag_queries(
        product=Product.WEB_ANALYTICS,
        feature=Feature.DIGEST,
        name="wa_digest_notification",
    )

    totals = DigestBatchResult(batch_size=len(input.org_ids))

    for org_id in input.org_ids:
        try:
            org_counts = _build_and_send_for_org(org_id, flag_key=input.flag_key, dry_run=input.dry_run)
        except Exception as e:
            logger.exception("WA digest notification failed for org", org_id=org_id, error=str(e))
            capture_exception(e, {"org_id": org_id})
            totals.orgs_failed += 1
            continue

        if org_counts.skipped_reason is not None:
            totals.orgs_skipped += 1
            continue

        totals.orgs_processed += 1
        totals.notifications_sent += org_counts.sent
        totals.control_exposed += org_counts.control
        totals.skipped_no_data += org_counts.skipped_no_data
        totals.failed += org_counts.failed
        totals.build_duration += org_counts.build_duration
        totals.send_duration += org_counts.send_duration

    return totals


def _get_org_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
    close_old_connections()

    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info(
            "skipping wa digest notification due to clickhouse kill switch",
            kill_switch_level=kill_switch_level.value,
        )
        return OrgBatchPageResult(batches=[], cursor=None)

    workflow_input = input.workflow_input

    if workflow_input.org_ids:
        page_org_ids, next_cursor = paginate_index(list(workflow_input.org_ids), input.cursor, input.page_size)
        source = "configured"
    else:
        page_org_ids, next_cursor = paginate_keyset(Organization.objects.all(), input.cursor, input.page_size)
        source = "keyset"

    batches = [list(b) for b in batched(page_org_ids, workflow_input.batch_size, strict=False)]
    logger.info(
        "wa digest notification org batch page",
        source=source,
        count=len(page_org_ids),
        batch_count=len(batches),
        batch_size=workflow_input.batch_size,
        cursor=input.cursor,
        next_cursor=next_cursor,
    )
    return OrgBatchPageResult(batches=batches, cursor=next_cursor)


def _send_test_digest_notification(email: str, team_id: int | None = None) -> None:
    close_old_connections()

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        raise ValueError(f"No active user found with email {email}")

    if team_id is not None:
        team = Team.objects.select_related("organization").filter(id=team_id).first()
        if not team:
            raise ValueError(f"Team {team_id} not found")

        membership = OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user_id=user.id,
        ).first()
        if not membership:
            raise PermissionError(f"User {email} is not a member of the organization that owns team {team_id}")

        digest = build_team_digest(team)
        accessible = _accessible_team_data(user, team.organization, membership, {team.id: digest})
        if not accessible:
            raise PermissionError(f"User {email} does not have access to team {team_id}")

        outcome = _send_digest_notification(
            user=user,
            org=team.organization,
            team_digest_data=accessible,
            variant="test",
        )
        if outcome != NotificationDigestOutcome.SENT:
            raise RuntimeError(
                f"Test digest notification not delivered for team {team_id} "
                f"(real-time-notifications disabled or no recipients)"
            )

        logger.info(
            "Sent test WA digest notification",
            mode="single_team",
            team_id=team_id,
            team_name=team.name,
            email=email,
        )
        return

    memberships = list(OrganizationMembership.objects.select_related("organization").filter(user_id=user.id))
    if not memberships:
        raise ValueError(f"User {email} has no organization memberships")

    sent_count = 0
    for membership in memberships:
        org = membership.organization
        team_digest_data = {t.id: build_team_digest(t) for t in Team.objects.filter(organization_id=org.id)}
        accessible = _accessible_team_data(user, org, membership, team_digest_data)
        if not accessible:
            continue
        outcome = _send_digest_notification(
            user=user,
            org=org,
            team_digest_data=accessible,
            variant="test",
        )
        if outcome == NotificationDigestOutcome.SENT:
            sent_count += 1

    if sent_count == 0:
        raise RuntimeError(
            f"No test digest notifications delivered for {email} "
            f"(no accessible teams, or real-time-notifications disabled in their orgs)"
        )

    logger.info(
        "Sent test WA digest notification",
        mode="full_user_digest",
        email=email,
        notifications_sent=sent_count,
    )


@activity.defn(name="wa-digest-notif-get-org-batch-page")
async def get_org_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
    return await database_sync_to_async(_get_org_batch_page, thread_sensitive=False)(input)


@activity.defn(name="wa-digest-notif-run-batch")
async def run_wa_digest_notification_batch(input: DigestBatchInput) -> DigestBatchResult:
    async with Heartbeater():
        return await database_sync_to_async(_run_wa_digest_notification_batch, thread_sensitive=False)(input)


@activity.defn(name="wa-digest-notif-send-test")
async def send_test_wa_digest_notification(input: SendTestDigestNotificationInput) -> None:
    await database_sync_to_async(_send_test_digest_notification, thread_sensitive=False)(input.email, input.team_id)
