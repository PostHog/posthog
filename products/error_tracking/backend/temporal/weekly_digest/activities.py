import json
from collections import Counter
from typing import Literal

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

import structlog
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.messaging import MessagingRecord
from posthog.storage import object_storage
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.user_permissions import UserPermissions

from products.error_tracking.backend import weekly_digest, weekly_digest_delivery
from products.error_tracking.backend.facade.contracts import ExceptionSummary
from products.error_tracking.backend.temporal.weekly_digest.types import (
    CleanupDigestOrgsInputs,
    GetDigestOrgsInputs,
    GetDigestOrgsResult,
    LoadPageOrgsInputs,
    SendOrgDigestInputs,
    SendOrgDigestResult,
)

logger = structlog.get_logger(__name__)


def _get_digest_orgs(inputs: GetDigestOrgsInputs) -> GetDigestOrgsResult:
    """Resolve the full sorted set of org ids for this run and stash it in object storage.

    An explicit ``org_ids`` (manual targeted runs) bypasses discovery; scheduled runs
    discover every org with exceptions. Discovery's exception-count scan runs once per
    run instead of once per page; page children read their slice back via
    ``load_page_orgs_activity``, so the full list never rides through a Temporal payload.

    Writing before returning makes retries idempotent: a retry overwrites the same key
    with a fresh list and the count always describes the object that was just written.
    """
    # Checked before org_ids so a targeted manual run can't route around the cloud gate. Returning
    # no orgs is what keeps the page children from being scheduled at all.
    if not is_cloud():
        logger.info("Skipping Error Tracking weekly digest outside PostHog Cloud")
        return GetDigestOrgsResult(total_orgs=0)

    if inputs.org_ids is not None:
        org_ids = sorted(str(org_id) for org_id in inputs.org_ids)
    else:
        org_ids = sorted(str(org_id) for org_id in weekly_digest.get_org_ids_with_exceptions())

    if org_ids:
        object_storage.write(inputs.storage_key, json.dumps(org_ids))
    return GetDigestOrgsResult(total_orgs=len(org_ids))


@activity.defn
def get_digest_orgs_activity(inputs: GetDigestOrgsInputs) -> GetDigestOrgsResult:
    close_old_connections()
    return _get_digest_orgs(inputs)


def _load_page_orgs(inputs: LoadPageOrgsInputs) -> list[str]:
    """Read one page's org ids back from the list discovery stored.

    A missing object raises (activity retries): the parent always writes before starting
    children, so absence means storage trouble, not an empty page.
    """
    content = object_storage.read(inputs.storage_key)
    if content is None:
        raise ApplicationError(f"Digest org list not found in object storage at {inputs.storage_key}")
    org_ids = json.loads(content)
    start = (inputs.page_number - 1) * inputs.page_size
    return org_ids[start : start + inputs.page_size]


@activity.defn
def load_page_orgs_activity(inputs: LoadPageOrgsInputs) -> list[str]:
    return _load_page_orgs(inputs)


@activity.defn
def cleanup_digest_orgs_activity(inputs: CleanupDigestOrgsInputs) -> None:
    object_storage.delete(inputs.storage_key)


_DeliveryOutcome = Literal["skipped", "deferred", "sent", "sent_lacking", "already_sent", "failed"]


@frozen
class _AutoselectRanking:
    counts_by_team: dict[int, ExceptionSummary]
    # Kept for the build phase: the 14-day row query is the most expensive thing this activity does, so a
    # team ranked here shouldn't pay for it again when its digest is built.
    daily_rows_by_team: dict[int, list]


@frozen
class _Recipient:
    membership: OrganizationMembership
    enabled_team_ids: list[int]
    disabled_team_names: list[str]


@frozen
class _TeamDigestBuild:
    data_by_team: dict[int, dict]
    failed_team_ids: list[int]


def _rank_teams_for_autoselect(
    memberships: list[OrganizationMembership],
    all_org_teams: dict[int, Team],
    team_ids_with_exceptions: set[int],
    org_id: str,
) -> _AutoselectRanking:
    """Rank teams by test-account-filtered exception counts for first-time user auto-enrollment.

    First-time users are auto-enrolled onto their busiest project. Ranking must use test-account-filtered
    counts: unfiltered counts can permanently enroll a user onto a project whose digest builds empty
    (auto-select is a one-shot decision). Only computed when the org actually has a first-time user.
    """
    counts_by_team: dict[int, ExceptionSummary] = {}
    daily_rows_by_team: dict[int, list] = {}
    setting_key = weekly_digest.DIGEST_PROJECT_SETTING_KEY
    if any(setting_key not in (m.user.partial_notification_settings or {}) for m in memberships):
        for tid in team_ids_with_exceptions:
            try:
                daily_rows_by_team[tid] = weekly_digest.query_daily_rows(all_org_teams[tid])
            except Exception:
                # A team whose filtered query is permanently broken (bad regex, deleted cohort) must
                # not sink the whole org here, before the build phase can defer or fall back.
                # It just goes unranked, so auto-select can't enroll anyone onto it.
                logger.exception("et_weekly_digest.autoselect_rank_failed", team_id=tid, org_id=org_id)
                continue
            summary = weekly_digest.get_exception_summary_for_team(all_org_teams[tid], daily_rows_by_team[tid])
            if summary and summary.exception_count > 0:
                counts_by_team[tid] = summary
    return _AutoselectRanking(counts_by_team=counts_by_team, daily_rows_by_team=daily_rows_by_team)


def _plan_recipient(
    org: Organization,
    membership: OrganizationMembership,
    all_org_teams: dict[int, Team],
    team_ids_with_exceptions: set[int],
    autoselect_counts: dict[int, ExceptionSummary],
    dry_run: bool,
) -> _Recipient | None:
    """Resolve one member's enabled teams from notification settings and project access only (no ClickHouse)."""
    user = membership.user

    if not should_send_notification(user, NotificationSetting.ERROR_TRACKING_WEEKLY_DIGEST.value):
        return None

    # One instance per user: its membership and access-control prefetches are cached on the
    # instance, so rebuilding it per team would re-query them for every team in the org.
    user_permissions = UserPermissions(user)
    accessible_team_ids = {
        team_id
        for team_id in team_ids_with_exceptions
        if user_permissions.team(all_org_teams[team_id]).effective_membership_level_for_parent_membership(
            org, membership
        )
        is not None
    }

    # Rank only projects this member can open. Auto-select is one-shot and persisted, so enrolling
    # someone onto a project they can't reach leaves every other project disabled-by-omission and
    # silences their digest for good. A dry run only simulates it, so it can't consume the enrollment.
    if weekly_digest.auto_select_project_for_user(
        user,
        org.id,
        {tid: counts for tid, counts in autoselect_counts.items() if tid in accessible_team_ids},
        persist=not dry_run,
    ):
        user.refresh_from_db(fields=["partial_notification_settings"])

    enabled_team_ids: list[int] = []
    disabled_team_names: list[str] = []
    for team_id in accessible_team_ids:
        if should_send_notification(user, NotificationSetting.ERROR_TRACKING_WEEKLY_DIGEST.value, team_id):
            enabled_team_ids.append(team_id)
        else:
            disabled_team_names.append(all_org_teams[team_id].name)

    if not enabled_team_ids:
        return None
    return _Recipient(membership=membership, enabled_team_ids=enabled_team_ids, disabled_team_names=disabled_team_names)


def _build_team_digest(team: Team, daily_rows: list | None, unfiltered_fallback: bool, org_id: str) -> dict | None:
    """Build one team's digest data, or None when it has none. Raises when the build fails."""
    try:
        return weekly_digest.build_team_digest_data(team, daily_rows)
    except Exception:
        if not unfiltered_fallback:
            raise
        logger.exception("et_weekly_digest.team_build_filtered_failed", team_id=team.id, org_id=org_id)
    # No cached daily_rows: those were queried with the filters applied, and the
    # rebuilt sections must be consistently unfiltered.
    data = weekly_digest.build_team_digest_data(team, filter_test_accounts=False)
    logger.warning("et_weekly_digest.team_built_without_test_account_filters", team_id=team.id, org_id=org_id)
    return data


def _build_team_digests(
    all_org_teams: dict[int, Team],
    needed_team_ids: set[int],
    daily_rows_by_team: dict[int, list],
    unfiltered_fallback: bool,
    org_id: str,
) -> _TeamDigestBuild:
    """Build digest data only for teams a recipient has enabled.

    A team whose build fails is recorded in failed_team_ids; recipients not subscribed to it are
    unaffected, while those who are get held back for the retry.
    """
    data_by_team: dict[int, dict] = {}
    failed_team_ids: list[int] = []
    for team_id in needed_team_ids:
        try:
            data = _build_team_digest(
                all_org_teams[team_id], daily_rows_by_team.get(team_id), unfiltered_fallback, org_id
            )
        except Exception:
            logger.exception("et_weekly_digest.team_build_failed", team_id=team_id, org_id=org_id)
            failed_team_ids.append(team_id)
            continue
        if data:
            data_by_team[team_id] = data
    return _TeamDigestBuild(data_by_team=data_by_team, failed_team_ids=failed_team_ids)


def _claim_and_send(
    digest: dict, user: User, distinct_id: str, campaign_key: str, org_id: str
) -> Literal["sent", "already_sent", "failed"]:
    # Claim the recipient before handing the digest to the workflow, not after. The send is an
    # irreversible external call, so writing sent_at afterwards leaves a window where a failed
    # commit rolls the marker back and the retry sends the same digest twice. Claiming first
    # inverts that: releasing the claim on a failed send keeps the retry working, and a crash
    # between the two costs one missed digest rather than a duplicate.
    record, _ = MessagingRecord.objects.get_or_create(raw_email=user.email, campaign_key=campaign_key)
    claimed = MessagingRecord.objects.filter(pk=record.pk, sent_at__isnull=True).update(sent_at=timezone.now())
    if not claimed:
        return "already_sent"

    try:
        weekly_digest_delivery.send_digest_to_workflow(digest, distinct_id)
    except Exception:
        logger.exception("et_weekly_digest.send_failed", user_id=str(user.uuid), org_id=org_id)
        MessagingRecord.objects.filter(pk=record.pk).update(sent_at=None)
        return "failed"
    return "sent"


def _deliver_to_recipient(
    org: Organization,
    org_id: str,
    recipient: _Recipient,
    build: _TeamDigestBuild,
    excluded_project_count: int,
    is_final_attempt: bool,
    dry_run: bool,
    date_suffix: str,
) -> _DeliveryOutcome:
    """Build one recipient's digest and claim, send, and record it."""
    user = recipient.membership.user

    user_team_sections = [
        build.data_by_team[team_id] for team_id in recipient.enabled_team_ids if team_id in build.data_by_team
    ]
    if not user_team_sections:
        return "skipped"

    # Teams the recipient subscribes to that failed to build this run: a non-empty list means their
    # digest is "lacking" those sections. On non-final attempts, hold the recipient back: the retry
    # re-runs the build, so a transient failure still delivers their full digest. Only once retries
    # are exhausted do we send the partial, so a permanently-broken team can't starve a recipient of
    # their healthy teams. Recipients not subscribed to a failed team send immediately.
    missing_failed_team_ids = [team_id for team_id in recipient.enabled_team_ids if team_id in build.failed_team_ids]
    if not is_final_attempt and missing_failed_team_ids:
        return "deferred"

    user_team_sections.sort(key=lambda d: d["exception_count"], reverse=True)

    distinct_id = user.distinct_id or str(user.uuid)
    digest = {
        "recipient_email": user.email,
        "org_name": org.name,
        "project_sections": [weekly_digest_delivery.build_team_section_payload(d) for d in user_team_sections],
        "disabled_project_names": recipient.disabled_team_names,
        "excluded_project_count": excluded_project_count,
        "settings_url": f"{settings.SITE_URL}/settings/user-notifications?highlight=et-weekly-digest",
        "feedback_survey_url": f"https://us.posthog.com/external_surveys/019c7fd6-7cfa-0000-2b03-a8e5d4c03743?distinct_id={distinct_id}",
    }

    if dry_run:
        logger.info(
            "et_weekly_digest.dry_run_send",
            org_id=org_id,
            user_id=str(user.uuid),
            teams=len(user_team_sections),
        )
        return "sent"

    campaign_key = f"error_tracking_weekly_digest_{org_id}_{user.uuid}_{date_suffix}"
    outcome = _claim_and_send(digest, user, distinct_id, campaign_key, org_id)
    if outcome != "sent" or not missing_failed_team_ids:
        return outcome
    # A lacking digest actually went out (final-attempt fallback): the recipient is missing
    # these teams because their builds kept failing. Grep this event to audit lacking sends.
    logger.warning(
        "et_weekly_digest.lacking_digest_sent",
        org_id=org_id,
        user_id=str(user.uuid),
        missing_team_ids=missing_failed_team_ids,
        teams_sent=len(user_team_sections),
    )
    return "sent_lacking"


def _send_org_digest(inputs: SendOrgDigestInputs, attempt: int) -> SendOrgDigestResult:
    """Send one combined weekly error tracking digest per user in an org via the delivery workflow.

    ``attempt`` is Temporal's 1-based attempt counter; ``attempt >= inputs.max_attempts`` marks
    the final attempt, which sends partial digests instead of deferring recipients. On the last
    two attempts, a team whose filtered build fails is rebuilt without its test account filters,
    with the section flagged so the email can disclose it.
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
    ranking = _rank_teams_for_autoselect(memberships, all_org_teams, team_ids_with_exceptions, org_id)

    # Plan recipients before any digest build. This yields the set of teams at least one recipient will actually
    # receive, so the build phase builds heavy digest data for those alone instead of for every team in the org
    # that happens to have exceptions.
    recipients = [
        recipient
        for membership in memberships
        if (
            recipient := _plan_recipient(
                org, membership, all_org_teams, team_ids_with_exceptions, ranking.counts_by_team, inputs.dry_run
            )
        )
    ]
    needed_team_ids = {team_id for recipient in recipients for team_id in recipient.enabled_team_ids}

    date_suffix = timezone.now().strftime("%Y-%W")

    if not needed_team_ids:
        logger.info(f"Sent Error Tracking weekly digest to 0 members for org {org_id} (no subscribed recipients)")
        return SendOrgDigestResult()

    # A team still failing this deep into the retries is most likely failing because of its test
    # account filters (broken regex, deleted cohort), which no retry will fix. The last two attempts
    # trade filtered accuracy for delivery: rebuild without the filters, and flag the section so the
    # email can disclose it. Keeping it off earlier attempts means a transient ClickHouse error
    # can't produce an unfiltered digest for a team whose filters work fine.
    unfiltered_fallback = attempt >= inputs.max_attempts - 1
    build = _build_team_digests(all_org_teams, needed_team_ids, ranking.daily_rows_by_team, unfiltered_fallback, org_id)

    # Org projects not represented as a section this week: no exceptions, no data after test-account
    # filtering, or a failed build. Teams a recipient disabled are named in their disabled list instead,
    # so they must not be counted here.
    excluded_project_count = (
        len(all_org_teams) - len(team_ids_with_exceptions) + (len(needed_team_ids) - len(build.data_by_team))
    )

    is_final_attempt = attempt >= inputs.max_attempts

    outcomes = Counter(
        _deliver_to_recipient(
            org, org_id, recipient, build, excluded_project_count, is_final_attempt, inputs.dry_run, date_suffix
        )
        for recipient in recipients
    )
    sent_count = outcomes["sent"] + outcomes["sent_lacking"]
    failed_count = outcomes["failed"]
    already_sent_count = outcomes["already_sent"]

    # Temporal only hands the workflow the final attempt's return value, so sent_count alone would lose
    # everything earlier attempts sent, down to zero for an org whose retry sends nothing new.
    sent_total = sent_count + already_sent_count

    # Every field except sent_total describes this attempt alone.
    logger.info(
        "et_weekly_digest.org_complete",
        org_id=org_id,
        attempt=attempt,
        is_final_attempt=is_final_attempt,
        dry_run=inputs.dry_run,
        sent=sent_count,
        already_sent=already_sent_count,
        sent_total=sent_total,
        lacking_sent=outcomes["sent_lacking"],
        teams_built=len(build.data_by_team),
        team_builds_failed=len(build.failed_team_ids),
        failed_team_ids=build.failed_team_ids,
        send_failures=failed_count,
        deferred=outcomes["deferred"],
    )

    if failed_count or build.failed_team_ids:
        # Trigger a Temporal retry; already-sent recipients are skipped via MessagingRecord, and
        # recipients missing a failed team were deferred above so the retry can complete them.
        # sent_total rides in the details because a raising activity returns no result.
        raise ApplicationError(
            f"Error Tracking weekly digest failed for {failed_count} recipients "
            f"and {len(build.failed_team_ids)} team builds in org {org_id}",
            sent_total,
        )

    return SendOrgDigestResult(sent=sent_total, teams_built=len(build.data_by_team))


@activity.defn
def send_org_digest_activity(inputs: SendOrgDigestInputs) -> SendOrgDigestResult:
    close_old_connections()
    attempt = activity.info().attempt
    with HeartbeaterSync(logger=logger):
        try:
            return _send_org_digest(inputs, attempt=attempt)
        except Exception:
            # Every other failure log sits inside the per-team build loop, so a failure before it
            # (the org-wide exception count query, or any Postgres read) names no org anywhere.
            # Temporal's own activity-failure log carries the activity id but not the inputs, which
            # leaves those orgs unidentifiable after the fact. This one event names the org for
            # every failure path: filter it on attempt == max_attempts for the orgs a run gave up on.
            logger.exception("et_weekly_digest.org_failed", org_id=inputs.org_id, attempt=attempt)
            raise
