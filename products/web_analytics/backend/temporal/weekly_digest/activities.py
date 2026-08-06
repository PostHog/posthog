import time
from datetime import datetime, timedelta
from itertools import batched

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from prometheus_client import Gauge
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.email import EmailMessage, is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.metrics import pushed_metrics_registry
from posthog.models import Team
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.user_permissions import UserPermissions

from products.web_analytics.backend.recap import recap_url_for_team
from products.web_analytics.backend.temporal.digest_common import paginate_index, paginate_keyset
from products.web_analytics.backend.temporal.weekly_digest.types import (
    WA_DIGEST_EMAIL_UNAVAILABLE_TYPE,
    DigestBatchInput,
    DigestBatchResult,
    DigestOutcome,
    OrgBatchPageInput,
    OrgBatchPageResult,
    OrgDigestCounts,
    SendTestDigestInput,
    WAWeeklyDigestInput,
)
from products.web_analytics.backend.weekly_digest import auto_select_project_for_user, build_team_digest

logger = structlog.get_logger(__name__)


def _get_org_queryset_for_digest(input: WAWeeklyDigestInput) -> tuple[QuerySet[Organization], datetime | None]:
    qs = Organization.objects.all()
    cutoff = None
    if input.active_since_days is not None and input.active_since_days > 0:
        cutoff = timezone.now() - timedelta(days=input.active_since_days)
        qs = qs.filter(
            Exists(
                OrganizationMembership.objects.filter(
                    organization_id=OuterRef("id"),
                    user__last_login__gte=cutoff,
                )
            )
        )
    return qs, cutoff


def _get_org_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
    """Raises non-retryable `ApplicationError` when email is globally unavailable
    — per-org skips would silently absorb the outage.
    """
    close_old_connections()

    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info(
            "skipping wa weekly digest due to clickhouse kill switch",
            kill_switch_level=kill_switch_level.value,
        )
        return OrgBatchPageResult(batches=[], cursor=None)

    if not is_email_available(with_absolute_urls=True):
        raise ApplicationError(
            "WA weekly digest: email service is unavailable",
            type=WA_DIGEST_EMAIL_UNAVAILABLE_TYPE,
            non_retryable=True,
        )

    workflow_input = input.workflow_input
    cutoff: datetime | None = None

    if workflow_input.org_ids:
        page_org_ids, next_cursor = paginate_index(list(workflow_input.org_ids), input.cursor, input.page_size)
        source = "configured"
    else:
        qs, cutoff = _get_org_queryset_for_digest(workflow_input)
        page_org_ids, next_cursor = paginate_keyset(qs, input.cursor, input.page_size)
        source = "keyset"

    batches = [list(b) for b in batched(page_org_ids, workflow_input.batch_size, strict=False)]
    logger.info(
        "wa digest org batch page",
        source=source,
        count=len(page_org_ids),
        batch_count=len(batches),
        batch_size=workflow_input.batch_size,
        cursor=input.cursor,
        next_cursor=next_cursor,
        active_since_days=workflow_input.active_since_days,
        cutoff=cutoff.isoformat() if cutoff else None,
    )
    return OrgBatchPageResult(batches=batches, cursor=next_cursor)


@activity.defn(name="wa-digest-get-org-batch-page")
async def get_org_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
    return await database_sync_to_async(_get_org_batch_page, thread_sensitive=False)(input)


def _send_digest_for_user(
    *,
    user: User,
    org: Organization,
    membership: OrganizationMembership,
    team_digest_data: dict[int, dict],
    date_suffix: str,
    dry_run: bool = False,
    test: bool = False,
) -> DigestOutcome:
    """`test=True` bypasses notification opt-ins and forces a unique
    campaign_key so dedupe never blocks delivery. Team-access checks are always
    enforced.
    """
    if not test and not should_send_notification(user, NotificationSetting.WEB_ANALYTICS_WEEKLY_DIGEST.value):
        return DigestOutcome.SKIPPED_OPTOUT

    user_perms = UserPermissions(user)
    accessible_team_data: dict[int, dict] = {}
    for team_id, data in team_digest_data.items():
        team = data["team"]
        if user_perms.team(team).effective_membership_level_for_parent_membership(org, membership) is not None:
            accessible_team_data[team_id] = data

    if not accessible_team_data:
        return DigestOutcome.SKIPPED_NO_DATA

    if auto_select_project_for_user(user, accessible_team_data):
        user.refresh_from_db(fields=["partial_notification_settings"])

    user_team_sections = []
    disabled_team_names = []
    for team_id, data in accessible_team_data.items():
        if test or should_send_notification(user, NotificationSetting.WEB_ANALYTICS_WEEKLY_DIGEST.value, team_id):
            user_team_sections.append(data)
        else:
            disabled_team_names.append(data["team"].name)

    if not user_team_sections:
        return DigestOutcome.SKIPPED_NO_DATA

    user_team_sections.sort(key=lambda d: d.get("visitors", {}).get("current", 0), reverse=True)

    campaign_key = f"web_analytics_weekly_digest_{org.id}_{user.uuid}_{date_suffix}"
    if test:
        campaign_key = f"{campaign_key}_test_{int(timezone.now().timestamp())}"

    if dry_run:
        return DigestOutcome.DRY_RUN

    # When the recap experience is enabled for this user, the email CTA points at the recap page.
    recap_enabled = _is_user_recap_enabled(user, str(org.id))
    if recap_enabled:
        for section in user_team_sections:
            section["recap_url"] = recap_url_for_team(
                section["team"], utm_source="web_analytics_weekly_digest", utm_medium="email"
            )

    try:
        message = EmailMessage(
            campaign_key=campaign_key,
            subject=f"Web analytics weekly digest for {org.name}",
            template_name="web_analytics_weekly_digest",
            template_context={
                "organization": org,
                "project_sections": user_team_sections,
                "disabled_project_names": disabled_team_names,
                "recap_enabled": recap_enabled,
                "settings_url": f"{settings.SITE_URL}/settings/user-notifications?highlight=wa-weekly-digest",
            },
        )
        message.add_user_recipient(user)
        message.send()
    except Exception as e:
        if test:
            raise
        logger.warning(
            "failed to send wa digest email",
            org_id=str(org.id),
            user_id=str(user.uuid),
            error=str(e),
        )
        capture_exception(e, {"org_id": str(org.id), "user_id": str(user.uuid)})
        return DigestOutcome.FAILED

    return DigestOutcome.SENT


def _is_user_flag_enabled(user: User, org_id: str, flag_key: str) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                distinct_id=str(user.distinct_id),
                groups={"organization": org_id},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        logger.warning(
            "wa digest: flag eval failed, treating user as not enabled",
            flag_key=flag_key,
            user_id=str(user.uuid),
            org_id=org_id,
            error=str(e),
        )
        capture_exception(e, {"user_id": str(user.uuid), "org_id": org_id})
        return False


def _is_user_recap_enabled(user: User, org_id: str) -> bool:
    return _is_user_flag_enabled(user, org_id, "web-analytics-recap")


def _is_user_targeted_for_digest(user: User, org_id: str) -> bool:
    return _is_user_flag_enabled(user, org_id, "web-analytics-weekly-digest")


def _build_and_send_for_org(org_id: str, dry_run: bool = False) -> OrgDigestCounts:
    close_old_connections()

    counts = OrgDigestCounts()

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning("Organization not found for WA weekly digest", org_id=org_id)
        counts.skipped_reason = "org_not_found"
        return counts

    memberships = list(OrganizationMembership.objects.prefetch_related("user").filter(organization_id=org.id))
    targeted_memberships = [m for m in memberships if _is_user_targeted_for_digest(m.user, str(org.id))]
    if not targeted_memberships:
        counts.skipped_reason = "no_targeted_memberships"
        return counts

    all_org_teams = list(Team.objects.filter(organization_id=org.id))
    if not all_org_teams:
        counts.skipped_reason = "no_teams"
        return counts

    build_start = time.monotonic()
    team_digest_data: dict[int, dict] = {team.id: build_team_digest(team) for team in all_org_teams}
    counts.build_duration = time.monotonic() - build_start
    counts.team_count = len(team_digest_data)

    date_suffix = timezone.now().strftime("%Y-%W")

    send_start = time.monotonic()
    for membership in targeted_memberships:
        outcome = _send_digest_for_user(
            user=membership.user,
            org=org,
            membership=membership,
            team_digest_data=team_digest_data,
            date_suffix=date_suffix,
            dry_run=dry_run,
        )
        if outcome in (DigestOutcome.SENT, DigestOutcome.DRY_RUN):
            counts.sent += 1
        elif outcome == DigestOutcome.SKIPPED_OPTOUT:
            counts.skipped_optout += 1
        elif outcome == DigestOutcome.SKIPPED_NO_DATA:
            counts.skipped_no_data += 1
        elif outcome == DigestOutcome.FAILED:
            counts.failed += 1
    counts.send_duration = time.monotonic() - send_start

    logger.info(
        "Sent WA weekly digest for org",
        org_id=org_id,
        sent_count=counts.sent,
        skipped_optout=counts.skipped_optout,
        skipped_no_data=counts.skipped_no_data,
        failed=counts.failed,
        team_count=counts.team_count,
    )
    return counts


def _run_wa_digest_batch(input: DigestBatchInput) -> DigestBatchResult:
    close_old_connections()

    tag_queries(
        product=Product.WEB_ANALYTICS,
        feature=Feature.DIGEST,
        name="wa_weekly_digest",
    )

    totals = DigestBatchResult(batch_size=len(input.org_ids))

    for org_id in input.org_ids:
        try:
            org_counts = _build_and_send_for_org(org_id, dry_run=input.dry_run)
        except Exception as e:
            logger.exception("WA digest failed for org", org_id=org_id, error=str(e))
            capture_exception(e, {"org_id": org_id})
            totals.orgs_failed += 1
            continue

        if org_counts.skipped_reason is not None:
            totals.orgs_skipped += 1
            continue

        totals.orgs_processed += 1
        totals.emails_sent += org_counts.sent
        totals.emails_skipped_optout += org_counts.skipped_optout
        totals.emails_skipped_no_data += org_counts.skipped_no_data
        totals.emails_failed += org_counts.failed
        totals.build_duration += org_counts.build_duration
        totals.send_duration += org_counts.send_duration

    return totals


@activity.defn(name="wa-digest-run-batch")
async def run_wa_digest_batch(input: DigestBatchInput) -> DigestBatchResult:
    """Per-org failures are isolated (logged and counted) so one bad org never poisons the batch."""
    async with Heartbeater():
        return await database_sync_to_async(_run_wa_digest_batch, thread_sensitive=False)(input)


def _push_wa_digest_metrics(totals: DigestBatchResult, success: bool) -> None:
    if not settings.PROM_PUSHGATEWAY_ADDRESS:
        return

    try:
        with pushed_metrics_registry("wa_weekly_digest") as registry:
            duration_gauge = Gauge(
                "posthog_wa_digest_duration_seconds",
                "Time spent in each phase of the WA weekly digest run (work time, summed across concurrent batches — not wall-clock)",
                labelnames=["phase"],
                registry=registry,
            )
            for phase, value in [
                ("build", totals.build_duration),
                ("send", totals.send_duration),
                ("cumulative", totals.total_duration),
            ]:
                duration_gauge.labels(phase=phase).set(value)

            orgs_gauge = Gauge(
                "posthog_wa_digest_orgs",
                "Org outcomes for a WA weekly digest run",
                labelnames=["outcome"],
                registry=registry,
            )
            for outcome, value in [
                ("total", totals.batch_size),
                ("processed", totals.orgs_processed),
                ("skipped", totals.orgs_skipped),
                ("failed", totals.orgs_failed),
            ]:
                orgs_gauge.labels(outcome=outcome).set(value)

            emails_gauge = Gauge(
                "posthog_wa_digest_emails",
                "Email outcomes for a WA weekly digest run",
                labelnames=["outcome"],
                registry=registry,
            )
            for outcome, value in [
                ("sent", totals.emails_sent),
                ("skipped_optout", totals.emails_skipped_optout),
                ("skipped_no_data", totals.emails_skipped_no_data),
                ("failed", totals.emails_failed),
            ]:
                emails_gauge.labels(outcome=outcome).set(value)

            success_gauge = Gauge(
                "posthog_wa_digest_success",
                "1 if the WA weekly digest run completed within failure threshold, else 0",
                registry=registry,
            )
            success_gauge.set(1 if success else 0)

            failure_rate_gauge = Gauge(
                "posthog_wa_digest_failure_rate",
                "Fraction of orgs whose processing raised an exception in the WA weekly digest",
                registry=registry,
            )
            failure_rate_gauge.set(totals.failure_rate)

            last_run_gauge = Gauge(
                "posthog_wa_digest_last_run_timestamp",
                "Unix timestamp of the most recent WA weekly digest run",
                registry=registry,
            )
            last_run_gauge.set(time.time())
    except Exception as e:
        logger.warning("Failed to push WA digest metrics to Pushgateway", error=str(e))
        capture_exception(e)


@activity.defn(name="wa-digest-push-metrics")
async def push_wa_digest_metrics_activity(totals_dict: dict, success: bool) -> None:
    totals = DigestBatchResult(**totals_dict)
    await database_sync_to_async(_push_wa_digest_metrics, thread_sensitive=False)(totals, success)


def _send_test_digest(email: str, team_id: int | None = None) -> None:
    """The recipient is the matched user's stored email, never the input string,
    so this cannot be used to redirect a team's data to an arbitrary inbox.
    """
    close_old_connections()

    if not is_email_available(with_absolute_urls=True):
        raise RuntimeError("Email is not available — check EMAIL_HOST in instance settings")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        raise ValueError(f"No active user found with email {email}")

    date_suffix = timezone.now().strftime("%Y-%W")

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

        outcome = _send_digest_for_user(
            user=user,
            org=team.organization,
            membership=membership,
            team_digest_data={team.id: build_team_digest(team)},
            date_suffix=date_suffix,
            test=True,
        )
        if outcome != DigestOutcome.SENT:
            raise PermissionError(f"User {email} does not have access to team {team_id}")

        logger.info(
            "Sent test WA digest",
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
        org_teams = list(Team.objects.filter(organization_id=org.id))
        if not org_teams:
            continue
        team_digest_data = {t.id: build_team_digest(t) for t in org_teams}
        outcome = _send_digest_for_user(
            user=user,
            org=org,
            membership=membership,
            team_digest_data=team_digest_data,
            date_suffix=date_suffix,
            test=True,
        )
        if outcome == DigestOutcome.SENT:
            sent_count += 1

    if sent_count == 0:
        raise PermissionError(f"User {email} has no accessible teams in any of their organizations")

    logger.info(
        "Sent test WA digest",
        mode="full_user_digest",
        email=email,
        emails_sent=sent_count,
    )


@activity.defn(name="wa-digest-send-test")
async def send_test_wa_digest(input: SendTestDigestInput) -> None:
    await database_sync_to_async(_send_test_digest, thread_sensitive=False)(input.email, input.team_id)
