from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

import structlog
from temporalio import activity

from posthog.cloud_utils import is_cloud
from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.messaging import MessagingRecord
from posthog.tasks.email import _DIGEST_PROJECT_SETTING_KEYS, NotificationSetting, should_send_notification
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.user_permissions import UserPermissions

from products.error_tracking.backend import weekly_digest
from products.error_tracking.backend.temporal.weekly_digest.types import (
    GetDigestOrgsInputs,
    SendOrgDigestInputs,
    SendOrgDigestResult,
)

logger = structlog.get_logger(__name__)


def _get_digest_orgs(inputs: GetDigestOrgsInputs) -> list[str]:
    """Resolve one keyset page of org ids for this run.

    An explicit ``org_ids`` (manual targeted runs) bypasses discovery; scheduled runs
    discover every org with exceptions. Cloud-only: the delivery webhook lives in the
    internal PostHog project, so a self-hosted run would ship digest data off-instance.

    The candidate set is sorted and sliced to (``after``, ``after`` + ``limit``] so the
    workflow can page with only a cursor. Recomputing candidates each page is safe: an
    org shifting in or out between pages is either <= cursor (already processed) or
    > cursor (still pending), never both.
    """
    if inputs.org_ids is not None:
        candidates = sorted(str(org_id) for org_id in inputs.org_ids)
    elif not is_cloud():
        logger.info("Skipping Error Tracking weekly digest discovery outside PostHog Cloud")
        return []
    else:
        candidates = sorted(str(org_id) for org_id in weekly_digest.get_org_ids_with_exceptions())

    if inputs.after is not None:
        candidates = [org_id for org_id in candidates if org_id > inputs.after]
    return candidates[: inputs.limit]


@activity.defn
def get_digest_orgs_activity(inputs: GetDigestOrgsInputs) -> list[str]:
    close_old_connections()
    return _get_digest_orgs(inputs)


def _send_org_digest(inputs: SendOrgDigestInputs, attempt: int) -> SendOrgDigestResult:
    """Send one combined weekly error tracking digest per user in an org via the delivery workflow.

    ``attempt`` is Temporal's 1-based attempt counter; ``attempt >= inputs.max_attempts`` marks
    the final attempt, which sends partial digests instead of deferring recipients.
    """
    org_id = inputs.org_id
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning(f"Organization {org_id} not found for Error Tracking weekly digest")
        return SendOrgDigestResult()

    all_org_teams = {t.id: t for t in Team.objects.filter(organization_id=org.id)}
    if not all_org_teams:
        return SendOrgDigestResult()

    # Which teams have any exceptions at all — one ClickHouse query for the whole org.
    unfiltered_counts = weekly_digest.get_exception_counts(list(all_org_teams.keys()))
    team_ids_with_exceptions = {row[0] for row in unfiltered_counts if row[0] in all_org_teams}
    if not team_ids_with_exceptions:
        return SendOrgDigestResult()

    memberships: list[OrganizationMembership] = list(
        OrganizationMembership.objects.prefetch_related("user").filter(organization_id=org.id)
    )

    # First-time users are auto-enrolled onto their busiest project. Ranking must use test-account-filtered
    # counts: unfiltered counts can permanently enroll a user onto a project whose digest builds empty
    # (auto-select is a one-shot decision). Only computed when the org actually has a first-time user.
    setting_key = _DIGEST_PROJECT_SETTING_KEYS[NotificationSetting.ERROR_TRACKING_WEEKLY_DIGEST.value]
    autoselect_counts: dict[int, dict] = {}
    if any(setting_key not in (m.user.partial_notification_settings or {}) for m in memberships):
        autoselect_counts = {
            tid: summary
            for tid in team_ids_with_exceptions
            if (summary := weekly_digest.get_exception_summary_for_team(all_org_teams[tid]))
            and summary["exception_count"] > 0
        }

    # Pass 1 — resolve each recipient's enabled teams from notification settings + project access only (no
    # ClickHouse). This yields the set of teams at least one recipient will actually receive, so Pass 2 builds
    # heavy digest data for those alone instead of for every team in the org that happens to have exceptions.
    recipients: list[tuple[OrganizationMembership, list[int], list[str]]] = []
    needed_team_ids: set[int] = set()
    for membership in memberships:
        user = membership.user

        if not should_send_notification(user, NotificationSetting.ERROR_TRACKING_WEEKLY_DIGEST.value):
            continue

        if weekly_digest.auto_select_project_for_user(user, org.id, autoselect_counts):
            user.refresh_from_db(fields=["partial_notification_settings"])

        enabled_team_ids: list[int] = []
        disabled_team_names: list[str] = []
        for team_id in team_ids_with_exceptions:
            team = all_org_teams[team_id]
            user_permissions = UserPermissions(user).team(team)
            if user_permissions.effective_membership_level_for_parent_membership(org, membership) is None:
                continue

            if should_send_notification(user, NotificationSetting.ERROR_TRACKING_WEEKLY_DIGEST.value, team_id):
                enabled_team_ids.append(team_id)
            else:
                disabled_team_names.append(team.name)

        if enabled_team_ids:
            recipients.append((membership, enabled_team_ids, disabled_team_names))
            needed_team_ids.update(enabled_team_ids)

    date_suffix = timezone.now().strftime("%Y-%W")

    if not needed_team_ids:
        logger.info(f"Sent Error Tracking weekly digest to 0 members for org {org_id} (no subscribed recipients)")
        return SendOrgDigestResult()

    # Pass 2 — build digest data only for teams a recipient has enabled. A team whose build fails is
    # recorded in failed_team_ids; recipients not subscribed to it are unaffected, while those who are
    # get held back for the retry (see is_final_attempt below). The activity re-raises at the end so
    # Temporal retries it.
    team_digest_data: dict[int, dict] = {}
    failed_team_ids: list[int] = []
    for team_id in needed_team_ids:
        try:
            data = weekly_digest.build_team_digest_data(all_org_teams[team_id])
        except Exception:
            logger.exception("et_weekly_digest.team_build_failed", team_id=team_id, org_id=org_id)
            failed_team_ids.append(team_id)
            continue
        if data:
            team_digest_data[team_id] = data

    # Org projects not represented as a section this week: no exceptions, no data after test-account
    # filtering, or a failed build. Teams a recipient disabled are named in their disabled list instead,
    # so they must not be counted here.
    excluded_project_count = (
        len(all_org_teams) - len(team_ids_with_exceptions) + (len(needed_team_ids) - len(team_digest_data))
    )

    # On non-final attempts, hold back a recipient whose digest is missing a team that failed to build
    # this run. The retry re-runs the build, so a transient failure still delivers their full digest.
    # Only once retries are exhausted do we fall back to sending the partial, so a permanently-broken
    # team can't starve a recipient of their healthy teams. Recipients not subscribed to a failed team
    # are unaffected and send immediately.
    failed_team_id_set = set(failed_team_ids)
    is_final_attempt = attempt >= inputs.max_attempts

    sent_count = 0
    failed_count = 0
    deferred_count = 0
    lacking_sent_count = 0

    for membership, enabled_team_ids, disabled_team_names in recipients:
        user = membership.user

        user_team_sections = [team_digest_data[team_id] for team_id in enabled_team_ids if team_id in team_digest_data]
        if not user_team_sections:
            continue

        # Teams the recipient subscribes to that failed to build this run: a non-empty list means their
        # digest is "lacking" those sections. Defer them off the final attempt; on it, send the partial.
        missing_failed_team_ids = [team_id for team_id in enabled_team_ids if team_id in failed_team_id_set]
        if not is_final_attempt and missing_failed_team_ids:
            deferred_count += 1
            continue

        user_team_sections.sort(key=lambda d: d["exception_count"], reverse=True)

        distinct_id = user.distinct_id or str(user.uuid)
        digest = {
            "recipient_email": user.email,
            "org_name": org.name,
            "project_sections": [weekly_digest.build_team_section_payload(d) for d in user_team_sections],
            "disabled_project_names": disabled_team_names,
            "excluded_project_count": excluded_project_count,
            "settings_url": f"{settings.SITE_URL}/settings/user-notifications?highlight=et-weekly-digest",
            "feedback_survey_url": f"https://us.posthog.com/external_surveys/019c7fd6-7cfa-0000-2b03-a8e5d4c03743?distinct_id={distinct_id}",
        }

        if inputs.dry_run:
            logger.info(
                "et_weekly_digest.dry_run_send",
                org_id=org_id,
                user_id=str(user.uuid),
                teams=len(user_team_sections),
            )
            sent_count += 1
            continue

        campaign_key = f"error_tracking_weekly_digest_{org_id}_{user.uuid}_{date_suffix}"
        # Per-recipient transaction + sent_at guard so a retry after a mid-batch
        # failure skips recipients whose digest was already accepted by the workflow.
        with transaction.atomic():
            record, _ = MessagingRecord.objects.get_or_create(raw_email=user.email, campaign_key=campaign_key)
            record = MessagingRecord.objects.select_for_update().get(pk=record.pk)
            if record.sent_at:
                continue

            try:
                weekly_digest.send_digest_to_workflow(digest, distinct_id)
            except Exception:
                logger.exception("et_weekly_digest.send_failed", user_id=str(user.uuid), org_id=org_id)
                failed_count += 1
                continue

            record.sent_at = timezone.now()
            record.save()
            sent_count += 1
            if missing_failed_team_ids:
                # A lacking digest actually went out (final-attempt fallback): the recipient is missing
                # these teams because their builds kept failing. Grep this event to audit lacking sends.
                lacking_sent_count += 1
                logger.warning(
                    "et_weekly_digest.lacking_digest_sent",
                    org_id=org_id,
                    user_id=str(user.uuid),
                    missing_team_ids=missing_failed_team_ids,
                    teams_sent=len(user_team_sections),
                )

    # Per-org, per-attempt summary. Counts are per-attempt but don't double-count across retries: each
    # recipient is sent (and counted) in exactly one attempt, then skipped via the sent_at guard. So
    # summing a field across an org's attempts gives the true total.
    logger.info(
        "et_weekly_digest.org_complete",
        org_id=org_id,
        attempt=attempt,
        is_final_attempt=is_final_attempt,
        dry_run=inputs.dry_run,
        sent=sent_count,
        lacking_sent=lacking_sent_count,
        teams_built=len(team_digest_data),
        team_builds_failed=len(failed_team_ids),
        failed_team_ids=failed_team_ids,
        send_failures=failed_count,
        deferred=deferred_count,
    )

    if failed_count or failed_team_ids:
        # Trigger a Temporal retry; already-sent recipients are skipped via MessagingRecord, and
        # recipients missing a failed team were deferred above so the retry can complete them.
        raise Exception(
            f"Error Tracking weekly digest failed for {failed_count} recipients "
            f"and {len(failed_team_ids)} team builds in org {org_id}"
        )

    return SendOrgDigestResult(sent=sent_count, teams_built=len(team_digest_data))


@activity.defn
def send_org_digest_activity(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
    close_old_connections()
    with HeartbeaterSync(logger=logger):
        return _send_org_digest(inputs, attempt=activity.info().attempt)
