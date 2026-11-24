import re
import time
from contextlib import suppress
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, connections, transaction
from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

import structlog
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from slack_sdk.errors import SlackApiError

from posthog.celery_queues import CeleryQueue
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, SlackIntegration
from posthog.models.organization import BillingPeriod
from posthog.models.scoping import with_team_scope
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit
from posthog.temporal.common.utils import is_stale_connection_read_only_error
from posthog.utils import UUID_REGEX

from products.signals.backend import report_assignments
from products.signals.backend.assignment_flags import assignment_side_effects_allowed
from products.signals.backend.billing import current_billing_period_bounds
from products.signals.backend.claim_takeover_notification import (
    send_claim_takeover_notification as send_claim_takeover_notification,
)
from products.signals.backend.constants import REPORT_POINTER_SWEEP_IDENTITY, SCRATCHPAD_REVISIONS_PER_KEY
from products.signals.backend.first_report_notification_tasks import (
    dispatch_first_report_notification as dispatch_first_report_notification,
    sweep_first_report_notifications as sweep_first_report_notifications,
)
from products.signals.backend.github_writeback_tasks import post_source_issue_links as post_source_issue_links
from products.signals.backend.handoff_claim_tasks import reconcile_task_handoff_claims as reconcile_task_handoff_claims
from products.signals.backend.implementation_dispatch_tasks import (
    dispatch_implementation_replacement as dispatch_implementation_replacement,
    sweep_implementation_dispatches as sweep_implementation_dispatches,
)
from products.signals.backend.implementation_pr import PrCloseReason, close_implementation_pr_for_report
from products.signals.backend.implementation_pr_cache import refresh_implementation_pr_cache_for_links
from products.signals.backend.implementation_pr_notification_tasks import (
    deliver_implementation_pr_notifications as deliver_implementation_pr_notifications,
)
from products.signals.backend.inbox_push_notifications import notify_pull_request_ready, notify_report_visible
from products.signals.backend.inbox_summary import github_datetime, sync_pull_request_participants
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportPullRequest,
    SignalReportRefund,
    SignalReportTrackerIssue,
    SignalRepositoryAreaActivity,
    SignalScoutEmission,
    SignalScoutRun,
    SignalScratchpad,
    SignalScratchpadRevision,
)
from products.signals.backend.personal_ranking_tasks import build_personal_inbox_ranking as build_personal_inbox_ranking
from products.signals.backend.pr_origin import write_origin_section
from products.signals.backend.pull_request_body import BodyEditOutcome
from products.signals.backend.pull_request_label import apply_pull_request_label
from products.signals.backend.pull_request_merger import PullRequestMerger
from products.signals.backend.pull_requests import update_pull_request_review_decision, update_pull_request_state
from products.signals.backend.rated_usage_tasks import (
    enqueue_signals_rated_usage as enqueue_signals_rated_usage,
    report_signals_rated_usage as report_signals_rated_usage,
)
from products.signals.backend.report_generation.repo_activity import (
    ACTIVITY_KEEP_WARM_WINDOW,
    rebuild_repository_activity,
    repository_activity_needs_rebuild,
)
from products.signals.backend.report_inbox_state import reconcile_report_inbox_state, teams_with_reports
from products.signals.backend.report_monitoring_signals import emit_due_monitoring_research
from products.signals.backend.report_note_mentions import (
    send_report_note_mention_notifications as send_report_note_mention_notifications,
    send_report_note_mention_slack as send_report_note_mention_slack,
)
from products.signals.backend.reviewer_pr_assignment import deliver_pull_request_assignment
from products.signals.backend.reviewer_pr_ready import open_pull_request_ready_for_review
from products.signals.backend.scout_harness.background_bands import refresh_background_bands
from products.signals.backend.scout_harness.inactivity import sweep_inactive_scouts
from products.signals.backend.scout_harness.slack_delivery import (
    DELIVERABLE_REPORT_STATUSES,
    ScoutSlackOutputType,
    ScoutSlackPermanentDeliveryError,
    _ensure_dm_recipient_eligible,
    _newer_report_delivery_queued,
    _post_scout_report_thread_replies,
    _slack_channel_id,
    _slack_integration_for_project,
    clear_latest_scout_report_delivery,
    mark_latest_scout_report_delivery,
    post_scout_emission_to_slack,
    post_scout_report_to_slack,
    slack_api_error_code,
)
from products.signals.backend.signal_metadata import fetch_signals_for_report_sync
from products.signals.backend.slack_inbox_notifications import dispatch_reviewer_added_notifications
from products.signals.backend.slack_report_threads import record_scout_report_slack_replies, scout_report_slack_message
from products.signals.backend.spend_recovery import recover_incomplete_spend as recover_incomplete_spend
from products.signals.backend.support_writeback import (
    post_pull_request_to_tickets,
    task_can_write_support_ticket_update,
)
from products.signals.backend.tracker_issues import (
    close_tracker_issue_for_report,
    complete_monitoring_tracker_issues,
    link_pull_request_to_tracker_issue,
)
from products.tasks.backend.facade.repo_activity import RepositoryCommitActivityError

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def emit_report_ready_event_task(team_id: int, report_id: str, known_source_products: list[str] | None = None) -> None:
    """Produce `$signals_report_ready` off the request path. Its ClickHouse lookup must not hold the request that
    moved the report, and a bulk state change commits its reports one at a time. No retry: a produce is not
    idempotent, and a duplicate nudge costs a consumer more than a missed one."""
    from products.signals.backend.receivers import _is_safety_suppressed  # noqa: PLC0415
    from products.signals.backend.report_ready_event import emit_report_ready_event  # noqa: PLC0415

    emit_report_ready_event(
        team_id=team_id,
        report_id=report_id,
        is_safety_suppressed=_is_safety_suppressed,
        known_source_products=known_source_products,
    )


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
@with_team_scope()
def refresh_report_implementation_pr_cache(
    team_id: int,
    report_ids: list[str] | None = None,
    pull_request_ids: list[str] | None = None,
    task_ids: list[str] | None = None,
) -> None:
    """Retry a cached PR flag refresh that failed after its link write committed."""
    refresh_implementation_pr_cache_for_links(
        team_id=team_id,
        report_ids=report_ids or [],
        pull_request_ids=pull_request_ids or [],
        task_ids=task_ids or [],
    )


@shared_task(bind=True, ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
@with_team_scope()
def write_pull_request_to_support_tickets(self: Task, team_id: int, report_id: str, pr_url: str, task_id: str) -> None:
    if not task_can_write_support_ticket_update(team_id=team_id, report_id=report_id, task_id=task_id, pr_url=pr_url):
        return
    try:
        pr = report_assignments._pull_request_details(team_id, pr_url, raise_on_error=True)
    except GitHubRateLimitError as error:
        raise self.retry(exc=error, countdown=max(error.retry_after or 0, 60))
    if pr.state not in {SignalReportPullRequest.State.DRAFT, SignalReportPullRequest.State.OPEN}:
        return
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return
    signals = fetch_signals_for_report_sync(team, report_id, ch_user=ClickHouseUser.SIGNALS, workload=Workload.OFFLINE)
    post_pull_request_to_tickets(team, report_id, pr_url, signals)


@shared_task(
    bind=True,
    ignore_result=True,
    autoretry_for=(GitHubEgressBudgetExhausted, GitHubIntegrationError, OperationalError),
    retry_backoff=True,
    max_retries=5,
)
@with_team_scope()
def refresh_linked_pull_request_state(self: Task, team_id: int, pr_url: str) -> None:
    """Read a just-linked pull request from GitHub again and store any state it moved to.

    A webhook that lands between the link's GitHub lookup and its commit finds no stored pull request,
    so without this re-read the link keeps the stale state until the next webhook, which may never come.
    """
    try:
        details = report_assignments._pull_request_details(team_id, pr_url, raise_on_error=True)
    except GitHubRateLimitError as error:
        raise self.retry(exc=error, countdown=max(error.retry_after or 0, 60))
    if details.state == SignalReportPullRequest.State.UNKNOWN:
        return
    stored = (
        SignalReportPullRequest.objects.for_team(team_id)
        .filter(repository=details.repository, number=details.number)
        .values_list("state", flat=True)
        .first()
    )
    if stored is None or stored == details.state:
        return
    update_pull_request_state(
        team_id=team_id,
        repository=details.repository,
        number=details.number,
        state=details.state,
        merged_at=details.merged_at,
        merged_by=details.merged_by,
    )


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
@with_team_scope()
def launch_inbox_onboarding_job(self: Task, team_id: int, job: str) -> None:
    from products.signals.backend.onboarding_activation import (
        InboxOnboardingActivation,  # noqa: PLC0415 - keep the Temporal graph off task discovery
    )

    InboxOnboardingActivation(team_id).run(job, final_attempt=self.request.retries >= self.max_retries)


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=10,
    acks_late=True,
    reject_on_worker_lost=True,
)
@with_team_scope(canonical=True)
def settle_scout_spend(self: Task, team_id: int, run_id: str) -> None:
    from products.signals.backend.spend import (
        complete_task_spend,  # noqa: PLC0415 - keeps spend accounting off the task registration import path
    )

    complete_task_spend(team_id=team_id, run_id=run_id, final_attempt=self.request.retries >= self.max_retries)


@shared_task(
    name="products.signals.backend.tasks.refresh_pull_request_participants",
    ignore_result=True,
    bind=True,
    autoretry_for=(GitHubEgressBudgetExhausted, GitHubIntegrationError),
    retry_backoff=True,
    max_retries=5,
)
@with_team_scope()
def refresh_pull_request_participants(self, team_id: int, repository: str, pr_number: int) -> None:
    try:
        sync_pull_request_participants(team_id=team_id, repository=repository, pr_number=pr_number)
    except GitHubRateLimitError as error:
        raise self.retry(exc=error, countdown=max(error.retry_after or 0, 60))


@shared_task(
    name="products.signals.backend.tasks.refresh_pull_request_review_decision",
    ignore_result=True,
    autoretry_for=(GitHubEgressBudgetExhausted, GitHubIntegrationError, GitHubRateLimitError),
    retry_backoff=True,
    max_retries=5,
)
@with_team_scope()
def refresh_pull_request_review_decision(team_id: int, repository: str, pr_number: int) -> None:
    pr = (
        SignalReportPullRequest.objects.for_team(team_id)
        .filter(repository=repository.lower(), number=pr_number)
        .first()
    )
    if pr is None:
        return
    if pr.state == SignalReportPullRequest.State.MERGED:
        from products.signals.backend.pull_requests import schedule_participant_refresh

        schedule_participant_refresh(pr)

    github = GitHubIntegration.first_for_team_repository(
        team_id,
        repository,
        source="signals_pr_review_decision",
        priority=Priority.BATCH,
    )
    if github is None:
        return
    if pr.state == SignalReportPullRequest.State.MERGED and pr.merged_at is None:
        details = github.get_pull_request(pr.repository, pr.number)
        merged_at = github_datetime(details.get("merged_at"))
        if not details.get("success") or details.get("merged") is not True or merged_at is None:
            raise GitHubIntegrationError("Could not verify the pull request merge time")
        update_pull_request_state(
            team_id=team_id,
            repository=pr.repository,
            number=pr.number,
            state="merged",
            merged_at=merged_at,
            merged_by=PullRequestMerger.from_github(details.get("merged_by")),
        )
    snapshot = github.get_pull_request_snapshot(pr.url)
    if not snapshot.get("success"):
        logger.warning(
            "signals_pr_review_decision_refresh_failed",
            team_id=team_id,
            repository=repository,
            pr_number=pr_number,
            error=snapshot.get("error"),
        )
        return
    # A state-change webhook writes the state its payload carried, so one handled late can store a
    # stale state over a newer one. This read is fresh, so it repairs that on the next PR event. A merge
    # stays with the paths that also record its merge time.
    snapshot_state = snapshot.get("state")
    if (
        pr.state != SignalReportPullRequest.State.MERGED
        and snapshot_state != pr.state
        and snapshot_state
        in {
            SignalReportPullRequest.State.DRAFT,
            SignalReportPullRequest.State.OPEN,
            SignalReportPullRequest.State.CLOSED,
        }
    ):
        update_pull_request_state(team_id=team_id, repository=pr.repository, number=pr.number, state=snapshot_state)
    raw_review_decision = snapshot.get("review_decision")
    review_decision = raw_review_decision if isinstance(raw_review_decision, str) else None
    update_pull_request_review_decision(
        team_id=team_id,
        repository=repository,
        number=pr_number,
        review_decision=review_decision,
    )


@shared_task(
    bind=True,
    ignore_result=True,
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    soft_time_limit=210,
    time_limit=240,
    acks_late=True,
    reject_on_worker_lost=True,
)
@with_team_scope()
def reconcile_implementation_replacement(self, team_id: int, replacement_id: str) -> None:
    from products.signals.backend.supersession import reconcile_replacement

    if reconcile_replacement(team_id, replacement_id):
        raise self.retry(countdown=min(60 * (2**self.request.retries), 900))


# Bounded exponential backoff: 2m, 4m, 8m, ... capped at 1h, 8 retries ≈ 5h total. Deliberately
# NOT unbounded — a hard failure should land with the sweeper (and its 7-day horizon) rather
# than retry forever. Rollover itself is survivable: the payload reports the period bounds
# frozen on the refund row, and billing credits against that period as long as it is still the
# customer's immediately-previous one.
_REFUND_SYNC_MAX_RETRIES = 8
_REFUND_SYNC_RETRY_BASE_SECONDS = 120
_REFUND_SYNC_RETRY_MAX_SECONDS = 3600

# Sweeper horizon: stop re-enqueueing unsynced credited refunds after 7 days. Anything older is
# an operational problem surfaced by the failure analytics event, handled manually (a billing
# admin creates the credit with idempotency key `signals_pr_dispute:{billing_customer_id}:{refund_id}`;
# the row then syncs as already_processed on any later attempt).
_REFUND_SYNC_SWEEP_MAX_AGE = timedelta(days=7)

# Billing answered a handled $0 because it could no longer credit the period the refund was
# accepted in — the sync outran billing's late-credit horizon (the frozen period is no longer
# the customer's current or immediately-previous one), or the row predates the frozen period
# bounds. Terminal for automation: retrying recomputes the same $0 (the frozen period only gets
# older), so the sweeper skips these rows and recovery is the documented manual credit path.
_OUT_OF_PERIOD_SYNC_ERROR = "billing: refund period no longer creditable at sync time; credit needs manual recovery"

_SCOUT_SLACK_MAX_RETRIES = 5
_SCOUT_SLACK_RETRY_BASE_SECONDS = 60
_SCOUT_SLACK_RETRY_MAX_SECONDS = 3600


@shared_task(
    name="products.signals.backend.tasks.close_dismissed_report_pr",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def close_dismissed_report_pr(
    report_id: str, team_id: int, reason: PrCloseReason = "suppressed", actor_user_id: int | None = None
) -> None:
    close_implementation_pr_for_report(team_id, report_id, reason=reason, actor_user_id=actor_user_id)
    # Suppression and snoozing are reversible. Keep their tracker issue open for a restored report.
    if reason == "resolved":
        close_report_tracker_issue.delay(
            report_id=report_id, team_id=team_id, completed=False, actor_user_id=actor_user_id
        )


@shared_task(
    name="products.signals.backend.tasks.close_report_tracker_issue",
    ignore_result=True,
    bind=True,
    max_retries=5,
    soft_time_limit=45,
    time_limit=60,
)
@with_team_scope()
def close_report_tracker_issue(
    self, report_id: str, team_id: int, completed: bool = False, actor_user_id: int | None = None
) -> None:
    if close_tracker_issue_for_report(
        team_id=team_id, report_id=report_id, completed=completed, actor_user_id=actor_user_id
    ):
        return
    retry_needed = (
        SignalReportTrackerIssue.objects.for_team(team_id)
        .filter(
            report_id=report_id,
            status__in=[SignalReportTrackerIssue.Status.PENDING, SignalReportTrackerIssue.Status.CREATED],
            closed_at__isnull=True,
        )
        .exists()
    )
    if retry_needed:
        raise self.retry(countdown=min(60 * (2**self.request.retries), 900))


@shared_task(ignore_result=True, soft_time_limit=45, time_limit=60)
@skip_team_scope_audit
def sweep_monitoring_tracker_issues() -> None:
    complete_monitoring_tracker_issues(deadline=time.monotonic() + 40)


@shared_task(ignore_result=True, soft_time_limit=45, time_limit=60)
@skip_team_scope_audit
def sweep_monitoring_research_requests() -> None:
    emit_due_monitoring_research(deadline=time.monotonic() + 40, limit=100)


@shared_task(ignore_result=True, soft_time_limit=120, time_limit=150)
@skip_team_scope_audit
def sweep_stuck_research_reports() -> None:
    from products.signals.backend.research_recovery import (
        recover_stuck_research_reports,  # noqa: PLC0415 — keeps the temporal deps off the import path
    )

    recover_stuck_research_reports()


@shared_task(
    name="products.signals.backend.tasks.link_report_tracker_issues",
    ignore_result=True,
    bind=True,
    max_retries=5,
)
@with_team_scope()
def link_report_tracker_issues(self, team_id: int, task_id: str, pr_url: str) -> None:
    """Write a task's new pull request body: the Origin section and the tracker issue cross-reference.

    Both edits share this task so they run in sequence. Two tasks would race on the same body and
    keep failing each other's changed-body check.
    """
    report_ids = SignalReport.pr_target_report_ids_for_tasks(team_id, [task_id])
    # A task with several reports attaches its PR to the reports it fixes explicitly.
    if (parsed := GitHubIntegration.parse_pull_request_url(pr_url)) is not None:
        report_ids.update(
            str(report_id)
            for report_id in SignalReportArtefact.objects.filter(
                team_id=team_id,
                type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
                task_id=task_id,
                pull_request__repository__iexact=parsed.repository,
                pull_request__number=parsed.number,
            ).values_list("report_id", flat=True)
        )
    retry_needed = False
    for report_id in sorted(report_ids):
        origin = write_origin_section(team_id=team_id, report_id=str(report_id), task_id=task_id, pr_url=pr_url)
        retry_needed = retry_needed or origin == BodyEditOutcome.FAILED
        linked = link_pull_request_to_tracker_issue(team_id=team_id, report_id=str(report_id), pr_url=pr_url)
        if not linked:
            retry_needed = (
                retry_needed
                or SignalReportTrackerIssue.objects.for_team(team_id)
                .filter(
                    # PENDING counts too: a fast run can report its pull request while the
                    # provider call is still in flight, and that issue still needs the reference.
                    report_id=report_id,
                    status__in=(
                        SignalReportTrackerIssue.Status.CREATED,
                        SignalReportTrackerIssue.Status.PENDING,
                    ),
                    pr_linked_at__isnull=True,
                    closed_at__isnull=True,
                )
                .exists()
            )
    if retry_needed:
        raise self.retry(countdown=min(60 * (2**self.request.retries), 900))


def _slack_retry_after_seconds(exc: Exception) -> int | None:
    if not isinstance(exc, SlackApiError) or not exc.response:
        return None
    headers = exc.response.headers or {}
    raw_value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        retry_after = int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        return None
    return retry_after if retry_after is not None and retry_after > 0 else None


def _scout_slack_retry_countdown(exc: Exception, retries: int) -> int:
    backoff = min(_SCOUT_SLACK_RETRY_BASE_SECONDS * (2**retries), _SCOUT_SLACK_RETRY_MAX_SECONDS)
    retry_after = _slack_retry_after_seconds(exc)
    return min(max(backoff, retry_after or 0), _SCOUT_SLACK_RETRY_MAX_SECONDS)


@shared_task(
    name="products.signals.backend.tasks.deliver_scout_slack_thread_replies",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
@with_team_scope(canonical=True)
def deliver_scout_slack_thread_replies(
    team_id: int,
    integration_id: int,
    channel: str,
    thread_ts: str,
    delivery_id: str,
    reply_blocks: list[list[dict]],
    fallback: str,
    chunk_offset: int,
    attempt: int = 1,
    report_id: str | None = None,
    report_revision: str | None = None,
) -> None:
    """Continue a rate-limited report thread without holding or retrying the lead-message worker."""
    if report_id is not None and not assignment_side_effects_allowed(team_id=team_id, report_id=report_id):
        return
    team = Team.objects.only("project_id").get(id=team_id)
    integration = _slack_integration_for_project(integration_id=integration_id, project_id=team.project_id)
    slack = SlackIntegration(integration, source="signals_scout")
    channel_id = _slack_channel_id(channel)

    def _schedule_retry(
        countdown: int,
        blocks: list[list[dict]],
        offset: int,
        retry_thread_ts: str,
        retry_fallback: str,
    ) -> None:
        if attempt >= _SCOUT_SLACK_MAX_RETRIES:
            logger.warning(
                "scout_slack_report_thread_reply_exhausted",
                team_id=team_id,
                integration_id=integration_id,
                channel=channel_id,
                delivery_id=delivery_id,
                chunk_index=offset,
                attempts=attempt,
            )
            return
        deliver_scout_slack_thread_replies.apply_async(
            kwargs={
                "team_id": team_id,
                "integration_id": integration_id,
                "channel": channel,
                "thread_ts": retry_thread_ts,
                "delivery_id": delivery_id,
                "reply_blocks": blocks,
                "fallback": retry_fallback,
                "chunk_offset": offset,
                "attempt": attempt + 1,
                **({"report_id": report_id} if report_id is not None else {}),
                **({"report_revision": report_revision} if report_revision is not None else {}),
            },
            countdown=countdown,
        )

    if report_id is not None:
        report = SignalReport.objects.filter(id=report_id, team_id=team_id).only("status", "updated_at").first()
        if report is None:
            logger.info("scout_slack_report_thread_reply_report_missing", team_id=team_id, report_id=report_id)
            return
        if report.status not in DELIVERABLE_REPORT_STATUSES:
            logger.info(
                "scout_slack_report_thread_reply_report_not_surfaced",
                team_id=team_id,
                report_id=report_id,
                report_status=report.status,
            )
            return
        if report_revision is not None and report.updated_at.isoformat() != report_revision:
            logger.info(
                "scout_slack_report_thread_reply_report_changed",
                team_id=team_id,
                report_id=report_id,
            )
            return
        if _newer_report_delivery_queued(report_id, delivery_id, integration_id, channel):
            logger.info(
                "scout_slack_report_thread_reply_yielded_to_newer_delivery",
                team_id=team_id,
                report_id=report_id,
                delivery_id=delivery_id,
            )
            return

    try:
        _ensure_dm_recipient_eligible(slack, channel_id)
    except ScoutSlackPermanentDeliveryError:
        raise
    except Exception as exc:
        _schedule_retry(
            _scout_slack_retry_countdown(exc, attempt - 1),
            reply_blocks,
            chunk_offset,
            thread_ts,
            fallback,
        )
        return

    # The earlier attempt recorded the replies it reached, so this one updates those instead of
    # posting them again.
    message = (
        scout_report_slack_message(
            team_id=team_id,
            report_id=report_id,
            slack_workspace_id=integration.integration_id or "",
            thread_ts=thread_ts,
        )
        if report_id is not None
        else None
    )

    def _record_reply_ts(posted: list[str]) -> None:
        if message is not None:
            record_scout_report_slack_replies(
                team_id=team_id,
                slack_workspace_id=integration.integration_id or "",
                channel=message.channel,
                thread_ts=thread_ts,
                reply_ts=posted,
            )

    _post_scout_report_thread_replies(
        slack.client,
        channel_id=channel_id,
        thread_ts=thread_ts,
        delivery_id=delivery_id,
        reply_blocks=reply_blocks,
        fallback=fallback,
        schedule_retry=_schedule_retry,
        chunk_offset=chunk_offset,
        conversation=message.channel if message is not None else None,
        reply_ts=message.reply_ts if message is not None else None,
        record_reply_ts=_record_reply_ts,
    )


@shared_task(
    name="products.signals.backend.tasks.deliver_scout_slack_output",
    ignore_result=True,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=_SCOUT_SLACK_MAX_RETRIES,
)
@with_team_scope(canonical=True)
def deliver_scout_slack_output(
    self,
    team_id: int,
    output_type: str,
    output_id: str,
    run_id: str,
    delivery_id: str,
    integration_id: int,
    channel: str,
    edit_note: str | None = None,
    thread_reports: bool = False,
) -> None:
    context = {
        "team_id": team_id,
        "output_type": output_type,
        "output_id": output_id,
        "run_id": run_id,
        "integration_id": integration_id,
    }
    try:
        if output_type == "finding":
            emission = (
                SignalScoutEmission.objects.select_related("scout_run", "team")
                .filter(id=output_id, team_id=team_id, scout_run_id=run_id)
                .first()
            )
            if emission is None:
                logger.warning("signals_scout.slack_delivery_output_missing", **context)
                return
            post_scout_emission_to_slack(
                emission,
                delivery_id=delivery_id,
                integration_id=integration_id,
                channel=channel,
            )
        elif output_type == "report":
            if not assignment_side_effects_allowed(team_id=team_id, report_id=output_id):
                return
            report = SignalReport.objects.select_related("team").filter(id=output_id, team_id=team_id).first()
            run = SignalScoutRun.objects.select_related("team").filter(id=run_id, team_id=team_id).first()
            if report is None or run is None:
                logger.warning("signals_scout.slack_delivery_output_missing", **context)
                return
            if report.status not in DELIVERABLE_REPORT_STATUSES:
                logger.info(
                    "signals_scout.slack_delivery_report_not_surfaced",
                    **context,
                    report_status=report.status,
                )
                return

            def _schedule_thread_reply_retry(
                countdown: int,
                blocks: list[list[dict]],
                offset: int,
                thread_ts: str,
                fallback: str,
            ) -> None:
                deliver_scout_slack_thread_replies.apply_async(
                    kwargs={
                        "team_id": team_id,
                        "integration_id": integration_id,
                        "channel": channel,
                        "thread_ts": thread_ts,
                        "delivery_id": delivery_id,
                        "reply_blocks": blocks,
                        "fallback": fallback,
                        "chunk_offset": offset,
                        "report_id": output_id,
                        "report_revision": report.updated_at.isoformat(),
                    },
                    countdown=countdown,
                )

            post_scout_report_to_slack(
                report,
                run,
                delivery_id=delivery_id,
                integration_id=integration_id,
                channel=channel,
                schedule_thread_reply_retry=_schedule_thread_reply_retry,
                edit_note=edit_note,
                thread_reports=thread_reports,
            )
        else:
            logger.warning("signals_scout.slack_delivery_output_type_invalid", **context)
            return
    except ScoutSlackPermanentDeliveryError as exc:
        capture_exception(exc, {**context, "error_code": exc.error_code})
        logger.warning(
            "signals_scout.slack_delivery_permanent_failure",
            **context,
            error_code=exc.error_code,
        )
        return
    except Exception as exc:
        if self.request.retries < _SCOUT_SLACK_MAX_RETRIES:
            countdown = _scout_slack_retry_countdown(exc, self.request.retries)
            logger.warning(
                "signals_scout.slack_delivery_retrying",
                **context,
                error_code=slack_api_error_code(exc) if isinstance(exc, SlackApiError) else None,
                attempt=self.request.retries + 1,
                countdown=countdown,
            )
            raise self.retry(exc=exc, countdown=countdown)

        capture_exception(
            exc,
            {
                **context,
                "error_code": slack_api_error_code(exc) if isinstance(exc, SlackApiError) else None,
                "attempts": self.request.retries + 1,
            },
        )
        logger.exception(
            "signals_scout.slack_delivery_exhausted",
            **context,
            attempts=self.request.retries + 1,
        )
        return

    logger.info("signals_scout.slack_delivery_sent", **context)


def enqueue_scout_slack_delivery(
    *,
    team_id: int,
    output_type: ScoutSlackOutputType,
    output_id: str,
    run_id: str,
    delivery_id: str,
    integration_id: int,
    channel: str,
    edit_note: str | None = None,
    thread_reports: bool = False,
) -> None:
    """Publish after commit, capturing broker failures without affecting the completed emit."""
    # Only a full report delivery supersedes an earlier one: a note-only update leaves the
    # report message to the delivery that is still building it.
    supersedes = output_type == "report" and edit_note is None
    try:
        if output_type == "report" and not assignment_side_effects_allowed(team_id=team_id, report_id=output_id):
            return
        # Claim before publishing: an earlier delivery of the same report reads this marker to decide
        # whether to yield, and between the two calls it would see no claim and post the report that
        # this delivery is about to post again.
        if supersedes:
            mark_latest_scout_report_delivery(output_id, delivery_id, integration_id, channel)
        # Each optional arg rides as a kwarg only when set, so a delivery without one keeps the
        # payload shape workers running the previous task signature still accept.
        extra_kwargs: dict[str, str | bool] = {}
        if edit_note is not None:
            extra_kwargs["edit_note"] = edit_note
        if thread_reports:
            extra_kwargs["thread_reports"] = True
        deliver_scout_slack_output.delay(
            team_id,
            output_type,
            output_id,
            run_id,
            delivery_id,
            integration_id,
            channel,
            **extra_kwargs,
        )
    except Exception as exc:
        # The claim now names a delivery that will never run, and would silence every later delivery
        # of this report until it expired, so give it up before reporting the failure.
        if supersedes:
            clear_latest_scout_report_delivery(output_id, delivery_id, integration_id, channel)
        capture_exception(
            exc,
            {
                "team_id": team_id,
                "output_type": output_type,
                "output_id": output_id,
                "run_id": run_id,
                "integration_id": integration_id,
            },
        )
        logger.exception(
            "signals_scout.slack_delivery_enqueue_failed",
            team_id=team_id,
            output_type=output_type,
            output_id=output_id,
            run_id=run_id,
            integration_id=integration_id,
        )


@shared_task(
    name="products.signals.backend.tasks.send_reviewer_added_slack_notifications",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def send_reviewer_added_slack_notifications(
    report_id: str,
    team_id: int,
    added_github_logins: list[str],
    exclude_user_id: int | None = None,
) -> None:
    """Slack-ping reviewers a human just added to a report.

    Runs on a worker because delivery makes several network calls (Slack user lookups,
    chat.postMessage) that must not hold up the reviewer-edit request.
    Best-effort end to end — the dispatcher logs per-destination failures itself.
    """
    github_logins = [value for value in added_github_logins if not value.startswith("user:")]
    user_uuids = [value.removeprefix("user:") for value in added_github_logins if value.startswith("user:")]
    dispatch_reviewer_added_notifications(
        report_id=report_id,
        team_id=team_id,
        added_github_logins=github_logins,
        added_user_uuids=user_uuids,
        exclude_user_id=exclude_user_id,
    )


# Bounded recovery for a transient GitHub failure on the first shared assignment: 1m, 2m, 4m, 8m,
# 15m, about half an hour in total. A later pull request event still queues a fresh attempt, so an
# exhausted retry is final only for this attempt and never sweeps other reports.
_FIRST_ASSIGNMENT_MAX_RETRIES = 5
_FIRST_ASSIGNMENT_RETRY_BASE_SECONDS = 60
_FIRST_ASSIGNMENT_RETRY_MAX_SECONDS = 900


@shared_task(
    name="products.signals.backend.tasks.assign_reviewers_on_implementation_pr",
    ignore_result=True,
    bind=True,
    max_retries=_FIRST_ASSIGNMENT_MAX_RETRIES,
)
@with_team_scope()
def assign_reviewers_on_implementation_pr(self, team_id: int, report_id: str, pr_url: str) -> None:
    """Assign an owner to the implementation PR and request a review.

    Runs on a worker because the GitHub calls (integration probe, PR read, assign) must not hold up
    the claim, sync, or reviewer edit that queued it. Every attempt re-reads the accepted list,
    corrections, access, delivery flags, and GitHub state, so a retry respects anything that changed
    in between and finds a write that did land as an existing assignment. A skipped attempt, such as
    one a disabled flag suppressed, is a decision and is never retried or replayed.
    """
    outcome = deliver_pull_request_assignment(team_id=team_id, report_id=report_id, pr_url=pr_url)
    if not outcome.retryable:
        return
    log = logger.bind(team_id=team_id, report_id=report_id, status=outcome.status, reason=outcome.reason)
    if self.request.retries >= self.max_retries:
        log.warning("signals.reviewer_pr_assignment.recovery_exhausted", attempts=self.request.retries + 1)
        return
    countdown = min(
        _FIRST_ASSIGNMENT_RETRY_BASE_SECONDS * (2**self.request.retries), _FIRST_ASSIGNMENT_RETRY_MAX_SECONDS
    )
    countdown = max(countdown, outcome.retry_after or 0)
    log.info("signals.reviewer_pr_assignment.recovery_scheduled", attempt=self.request.retries + 1, countdown=countdown)
    raise self.retry(countdown=countdown)


@shared_task(
    name="products.signals.backend.tasks.start_dependent_stack_layers",
    ignore_result=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    soft_time_limit=210,
    time_limit=240,
)
@with_team_scope()
def start_dependent_stack_layers(team_id: int, report_id: str) -> None:
    """Start the stack layers that wait on this report, now that it has a pull request.

    Runs on a worker because auto-start creates tasks and must not hold up the pull request sync
    that queued it. A failed layer start retries with backoff, because the next pull request event
    on the report may come only at merge, when the layer can no longer stack. A retry skips the
    layers that already started.
    """
    from products.signals.backend.stack_plan import start_dependent_layers  # noqa: PLC0415

    start_dependent_layers(team_id=team_id, report_id=report_id)


@shared_task(
    name="products.signals.backend.tasks.open_implementation_pr_for_review",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def open_implementation_pr_for_review(team_id: int, report_id: str, pr_url: str) -> None:
    """Take a report's implementation PR out of draft when its suggested reviewers asked for that.

    Runs on a worker for the same reason as reviewer assignment: the GitHub calls must not hold up
    the claim, sync, or webhook that queued it. Best-effort end to end, so this never retries.
    Unlike assignment, a retry could also fight a reviewer who redrafted the pull request in between.
    """
    open_pull_request_ready_for_review(team_id=team_id, report_id=report_id, pr_url=pr_url)


@shared_task(
    name="products.signals.backend.tasks.send_report_visible_push",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def send_report_visible_push(team_id: int, report_id: str) -> None:
    """Push a newly visible report to its suggested reviewers' mobile devices.

    Never retried, because a retry after a partial fan-out would push twice to the reviewers it
    already reached. The same holds for the pull request push below.
    """
    notify_report_visible(team_id=team_id, report_id=report_id)


@shared_task(
    name="products.signals.backend.tasks.send_pull_request_ready_push",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def send_pull_request_ready_push(team_id: int, pull_request_id: str) -> None:
    """Push a pull request that became ready for review to its reports' claimants and reviewers."""
    notify_pull_request_ready(team_id=team_id, pull_request_id=pull_request_id)


@shared_task(
    name="products.signals.backend.tasks.move_merged_report_signals",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def move_merged_report_signals(team_id: int, survivor_report_id: str, source_report_ids: list[str]) -> None:
    """Re-emit every merged-away report's ClickHouse signals under the surviving report's id.

    Runs on a worker because the merge's own transaction must not wait on a ClickHouse read plus
    one embedding emission per signal. The Postgres half of the merge is already committed and the
    survivor's counters were taken from the source rows, so the report is consistent while this is
    in flight; what the move buys is semantic search and future grouping pointing at the survivor.
    Best-effort, so this never retries: grouping follows the merge pointer in the meantime
    (`report_merge.merge_survivor`), which is what keeps a signal from re-attaching to the
    duplicate before the rows land.
    """
    from products.signals.backend.report_merge import (  # noqa: PLC0415 — keeps the merge module off the celery import path
        merge_survivor,
    )
    from products.signals.backend.temporal.signal_queries import (  # noqa: PLC0415 — keeps the temporal and hogql deps off the import path
        reassign_report_signals,
    )

    team = Team.objects.get(pk=team_id)
    # Two merges in quick succession (A into B, then B into C) queue two tasks that can run out of
    # order, so the survivor recorded at merge time may itself be merged away by now. Follow the
    # chain here instead, or A's signals land under the archived B and never reach C.
    survivor = SignalReport.objects.filter(team_id=team_id, id=survivor_report_id).first()
    if survivor is None:
        logger.warning(
            "signals_merged_report_signals_survivor_missing",
            team_id=team_id,
            survivor_report_id=survivor_report_id,
        )
        return
    survivor_report_id = str(merge_survivor(survivor).id)

    for source_report_id in source_report_ids:
        try:
            moved = reassign_report_signals(
                source_report_id=source_report_id,
                survivor_report_id=survivor_report_id,
                team_id=team_id,
                team=team,
            )
        except SoftTimeLimitExceeded:
            # Celery's own termination signal. Swallowing it would defeat the soft time limit.
            raise
        except Exception:
            # Each source is an independent ClickHouse read plus its own emissions, and the task
            # does not retry, so one source's failure must not strand the sources after it.
            logger.exception(
                "signals_merged_report_signals_move_failed",
                team_id=team_id,
                survivor_report_id=survivor_report_id,
                source_report_id=source_report_id,
            )
            continue
        logger.info(
            "signals_merged_report_signals_moved",
            team_id=team_id,
            survivor_report_id=survivor_report_id,
            source_report_id=source_report_id,
            signal_count=moved,
        )


@shared_task(
    name="products.signals.backend.tasks.label_implementation_pr",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def label_implementation_pr(team_id: int, report_id: str, pr_url: str) -> None:
    """Put the team's label on a report's implementation PR, so GitHub search can find it.

    Runs on a worker for the same reason as reviewer assignment: the GitHub calls must not hold up
    the claim, sync, or webhook that queued it. Best-effort end to end, so this never retries.
    """
    apply_pull_request_label(team_id=team_id, report_id=report_id, pr_url=pr_url)


def _capture_refund_sync_event(refund: SignalReportRefund, event: str, extra: dict[str, object]) -> None:
    organization = refund.team.organization
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(organization.id),
            event=event,
            properties={
                "team_id": refund.team_id,
                "organization_id": str(organization.id),
                "report_id": str(refund.report_id),
                "refund_id": str(refund.id),
                "credits": refund.credits,
                **extra,
            },
            groups=groups(organization=organization),
        )


@shared_task(
    name="products.signals.backend.tasks.sync_signals_refund_credit",
    ignore_result=True,
    bind=True,
    max_retries=_REFUND_SYNC_MAX_RETRIES,
)
@skip_team_scope_audit
def sync_signals_refund_credit(self, refund_id: str) -> None:
    """Report a credited-path refund to the billing dispute endpoint and record the outcome.

    Safe to re-deliver at any time (double-enqueue, sweeper overlap, manual re-run): billing is
    idempotent on `refund_id`, and an already-synced row returns immediately. User experience is
    unaffected while this lags — archive + badge + freed quota slot all happened at refund time;
    only the invoice credit waits.
    """
    from ee.billing.billing_manager import (
        BillingManager,  # noqa: PLC0415 — keeps the ee layer off the products import path (precedent: posthog/tasks/sync_billing.py)
    )

    refund = (
        # nosemgrep: idor-lookup-without-team (system Celery task keyed by refund id from our own enqueue/sweeper, no user input; unscoped is the sanctioned cross-team access)
        SignalReportRefund.objects.unscoped()
        .select_related("team__organization")
        .filter(id=refund_id, billing_path=SignalReportRefund.BillingPath.CREDITED)
        .first()
    )
    if refund is None:
        logger.warning("signals refund credit sync: no credited refund found", refund_id=refund_id)
        return
    if refund.billing_synced_at is not None:
        return

    organization = refund.team.organization
    # Report the period bounds frozen at refund acceptance, so billing credits against the
    # period the refund was accepted in even when this sync lands after rollover — recomputing
    # bounds here is exactly the drift that loses the credit. The fallback covers rows created
    # before the bounds were snapshotted.
    if refund.period_start is not None and refund.period_end is not None:
        period = BillingPeriod(start=refund.period_start, end=refund.period_end)
    else:
        period = current_billing_period_bounds(organization)
    payload = {
        "refund_id": str(refund.id),
        "credits": refund.credits,
        "metadata": {
            "team_id": refund.team_id,
            "report_id": str(refund.report_id),
            "pr_url": refund.pr_url,
            "pr_run_created_at": refund.pr_run_created_at.isoformat(),
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
        },
    }

    try:
        license = get_cached_instance_license()
        response = BillingManager(license, None).dispute_signals_pr(organization, payload)
        credit_amount_usd = Decimal(str(response["credit_amount_usd"]))
    except Exception as exc:
        if self.request.retries < _REFUND_SYNC_MAX_RETRIES:
            countdown = min(_REFUND_SYNC_RETRY_BASE_SECONDS * (2**self.request.retries), _REFUND_SYNC_RETRY_MAX_SECONDS)
            raise self.retry(exc=exc, countdown=countdown)
        # Terminal for this delivery — record the error for the weekly review; the hourly sweeper
        # keeps re-enqueueing the row for up to 7 days, after which recovery is operational. The
        # conditional update mirrors the success-path claim below: never stamp an error (or emit
        # the failed event) onto a row a concurrent delivery already synced.
        recorded = (
            # nosemgrep: idor-lookup-without-team (id comes from the sanctioned unscoped lookup above; system task, no user input)
            SignalReportRefund.objects.unscoped()
            .filter(id=refund.id, billing_synced_at__isnull=True)
            .update(billing_sync_error=str(exc)[:4000])
        )
        if recorded:
            capture_exception(exc, {"refund_id": str(refund.id), "team_id": refund.team_id})
            _capture_refund_sync_event(refund, "signals_pr_refund_credit_failed", {"error": str(exc)[:1000]})
        return

    if response.get("zero_reason") == "out_of_period":
        # The $0 means billing could no longer credit the frozen refund period (see
        # _OUT_OF_PERIOD_SYNC_ERROR), not that the refund was legitimately free. Record a sync
        # error instead of a synced $0 so the row surfaces for manual recovery.
        recorded = (
            # nosemgrep: idor-lookup-without-team (id comes from the sanctioned unscoped lookup above; system task, no user input)
            SignalReportRefund.objects.unscoped()
            .filter(id=refund.id, billing_synced_at__isnull=True)
            .update(billing_sync_error=_OUT_OF_PERIOD_SYNC_ERROR)
        )
        if recorded:
            capture_exception(
                Exception("signals refund credit lost to billing period rollover"),
                {"refund_id": str(refund.id), "team_id": refund.team_id},
            )
            _capture_refund_sync_event(refund, "signals_pr_refund_credit_failed", {"error": _OUT_OF_PERIOD_SYNC_ERROR})
        return

    # Atomic claim: the on-commit enqueue and the hourly sweeper can race two deliveries for the
    # same refund past the billing_synced_at gate above while the billing call is in flight
    # (billing stays idempotent, so the credit itself is issued once). Only the delivery that
    # flips the row records the sync and emits the issued event, keeping the weekly-review
    # analytics single-counted.
    claimed = (
        # nosemgrep: idor-lookup-without-team (id comes from the sanctioned unscoped lookup above; system task, no user input)
        SignalReportRefund.objects.unscoped()
        .filter(id=refund.id, billing_synced_at__isnull=True)
        .update(credit_amount_usd=credit_amount_usd, billing_synced_at=timezone.now(), billing_sync_error=None)
    )
    if not claimed:
        return
    _capture_refund_sync_event(
        refund,
        "signals_pr_refund_credit_issued",
        {
            "credit_amount_usd": str(credit_amount_usd),
            "already_processed": bool(response.get("already_processed")),
        },
    )


@shared_task(
    name="products.signals.backend.tasks.sync_pending_signals_refund_credits",
    ignore_result=True,
    max_retries=0,
)
@skip_team_scope_audit
def sync_pending_signals_refund_credits() -> None:
    """Hourly sweeper: re-enqueue credited refunds whose billing sync hasn't landed yet.

    Catches deliveries lost to worker crashes / deploys and rows whose bounded retries were
    exhausted while billing was down. Only rows younger than the sweep horizon are retried;
    re-enqueueing an already-synced row is a no-op in the task itself.
    """
    cutoff = timezone.now() - _REFUND_SYNC_SWEEP_MAX_AGE
    pending_ids = list(
        SignalReportRefund.objects.unscoped()
        .filter(
            billing_path=SignalReportRefund.BillingPath.CREDITED,
            billing_synced_at__isnull=True,
            created_at__gte=cutoff,
        )
        # Horizon-lost credits are terminal for automation — replaying returns the same $0.
        .exclude(billing_sync_error=_OUT_OF_PERIOD_SYNC_ERROR)
        .values_list("id", flat=True)
    )
    for refund_id in pending_ids:
        sync_signals_refund_credit.delay(str(refund_id))
    if pending_ids:
        logger.info("signals refund credit sweeper re-enqueued pending refunds", count=len(pending_ids))


_ACTIVITY_ROW_MAX_IDLE = timedelta(days=90)
# Every rebuild boots a Modal sandbox, so the weekly warm-up releases rebuilds in small batches
# spaced this far apart rather than all at once. A single burst of the whole fan-out trips
# Modal's API rate limit once enough repositories are warm. N repositories fully release in about
# (N / _REFRESH_BATCH_SIZE) * _REFRESH_BATCH_INTERVAL_SECONDS, well within the weekly cadence.
_REFRESH_BATCH_SIZE = 10
_REFRESH_BATCH_INTERVAL_SECONDS = 60
# Backstop for a worker dying without releasing the rebuild lock; above the task's
# time_limit so a live rebuild is never treated as abandoned.
_REBUILD_LOCK_TTL_SECONDS = 30 * 60


@shared_task(
    name="products.signals.backend.tasks.rebuild_signal_repository_activity",
    ignore_result=True,
    max_retries=0,
    # Sandbox clone (10m cap) + git log (3m cap) + attribution listing; the hard limit
    # backstops a hung sandbox call.
    soft_time_limit=20 * 60,
    time_limit=22 * 60,
)
@with_team_scope()
def rebuild_signal_repository_activity(team_id: int, repository: str, force: bool = False) -> None:
    """Rebuild one repository's area-activity map from its git history (sandbox clone + git log).

    Enqueued on cache miss by reviewer resolution and weekly by the sweeper (which passes
    ``force`` — its rows sit exactly at the staleness boundary). A failed rebuild leaves
    the cached rows untouched; the next enqueue retries.
    """
    # Concurrent enqueues for the same (team, repository) are common — several reports can
    # hit the same stale map before the first rebuild lands. The staleness re-check debounces
    # re-triggers over the freshness window; the atomic cache lock closes the remaining race
    # where several queued workers all pass the check before the first rebuild writes.
    if not force and not repository_activity_needs_rebuild(team_id, repository):
        return
    lock_key = f"signals_repo_activity_rebuild/{team_id}/{repository.strip().lower()}"
    if not cache.add(lock_key, "1", timeout=_REBUILD_LOCK_TTL_SECONDS):
        return
    try:
        rebuild_repository_activity(team_id, repository)
    except (RepositoryCommitActivityError, GitHubRateLimitError, GitHubEgressBudgetExhausted) as exc:
        # Expected deferrals (integration gone, rate limit, shed by the egress limiter) —
        # the map stays stale and the next enqueue retries.
        logger.warning(
            "signals repository activity rebuild deferred",
            team_id=team_id,
            repository=repository,
            error=str(exc),
        )
    except Exception as exc:
        capture_exception(exc, {"team_id": team_id, "repository": repository})
    finally:
        cache.delete(lock_key)


# Long enough to collapse a burst of reads into one queued build, short enough that a failed
# build is retried by the next read a few minutes later.
_PROFILE_BUILD_DEDUPE_SECONDS = 5 * 60


def enqueue_project_profile_build(team_id: int, *, dedupe: bool = True) -> None:
    """Queue one `build_signal_project_profile` per team per dedupe window.

    `dedupe=False` queues the build even inside the window. A read calls this after it has its
    profile, so a cache or broker failure is reported and does not fail the read. A failed
    enqueue releases the window, so the next read can queue the build again.
    """
    key = f"signals_project_profile_build/{team_id}"
    claimed = False
    try:
        claimed = cache.add(key, "1", timeout=_PROFILE_BUILD_DEDUPE_SECONDS)
        if claimed or not dedupe:
            build_signal_project_profile.delay(team_id)
    except Exception as exc:
        capture_exception(exc, {"team_id": team_id})
        if claimed:
            with suppress(Exception):
                cache.delete(key)


@shared_task(
    name="products.signals.backend.tasks.build_signal_project_profile",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def build_signal_project_profile(team_id: int) -> None:
    """Run the surface queries off the request path, and build the profile if the team has none.

    A read caller that found no profile queues this, and so does a read whose profile has no
    current surface entries.
    """
    # The `tools` package imports this module through `slack_delivery_queue`.
    from products.signals.backend.scout_harness.tools.profile import refresh_project_profile_surfaces  # noqa: PLC0415

    refresh_project_profile_surfaces(team_id=team_id)


@shared_task(
    name="products.signals.backend.tasks.refresh_signal_scout_background_bands",
    ignore_result=True,
    max_retries=0,
)
@skip_team_scope_audit
def refresh_signal_scout_background_bands() -> None:
    """Daily: recompute which projects can get a background scout, and their activity band.

    Runs here rather than on the coordinator tick, because it reads a week of fleet-wide event
    volume and activity bands do not change by the half hour.
    """
    outcome = refresh_background_bands()
    logger.info("signals_scout background bands refreshed", written=outcome.written, removed=outcome.removed)


@shared_task(
    name="products.signals.backend.tasks.reconcile_report_inbox_state_cache",
    ignore_result=True,
    max_retries=0,
)
@skip_team_scope_audit
def reconcile_report_inbox_state_cache() -> None:
    """Daily: correct cached implementation PR flags that drifted from the link tables, and count the drift."""
    corrected = failed = 0
    for team_id in teams_with_reports():
        try:
            corrected += reconcile_report_inbox_state(team_id)
        except Exception as error:
            failed += 1
            capture_exception(error, {"team_id": team_id})
    logger.info("signals report inbox state reconciled", implementation_pr=corrected, failed_teams=failed)


@shared_task(
    name="products.signals.backend.tasks.pause_inactive_signal_scouts",
    ignore_result=True,
    max_retries=0,
)
@skip_team_scope_audit
def pause_inactive_signal_scouts() -> None:
    """Daily sweep: warn, then auto-pause scouts nothing comes of.

    Runs here rather than on the coordinator's 30-minute tick — that tick is deliberately
    bounded, and inactivity doesn't change by the half hour. See
    `scout_harness/inactivity.py` for what counts as productive.
    """
    outcome = sweep_inactive_scouts()
    logger.info(
        "signals_scout inactivity sweep finished",
        considered=outcome.considered,
        warned=len(outcome.warned),
        paused=len(outcome.paused),
        recovered=outcome.recovered,
        deferred=outcome.deferred,
    )
    if not outcome.warned and not outcome.paused:
        return
    # The fleet's spend was measured from analytics in the first place, so report the sweep the same
    # way — it's how we'll tell whether the pauses are landing on the scouts we meant.
    touched = outcome.warned + outcome.paused
    organizations = {
        team.id: team.organization
        for team in Team.objects.filter(id__in={config.team_id for config in touched}).select_related("organization")
    }
    with ph_scoped_capture() as capture:
        for event, configs in (
            ("signals_scout_auto_pause_warned", outcome.warned),
            ("signals_scout_auto_paused", outcome.paused),
        ):
            for config in configs:
                organization = organizations.get(config.team_id)
                if organization is None:
                    continue
                capture(
                    distinct_id=str(organization.id),
                    event=event,
                    properties={
                        "team_id": config.team_id,
                        "organization_id": str(organization.id),
                        "skill_name": config.skill_name,
                        "run_interval_minutes": config.run_interval_minutes,
                        "pause_reason": config.pause_reason,
                        # Splits noisy-but-unconsumed from silent in the read-back; the two
                        # cohorts need different fixes (retune vs refocus).
                        "had_output": outcome.had_output.get(config.pk),
                    },
                    groups=groups(organization=organization),
                )


# Grace before a lapsed scratchpad entry is hard-deleted. Expiry already hides the row from scout
# searches; the grace keeps it readable through the `include_expired` audit path for two more weeks,
# so a human can still see what the fleet remembered and when it lapsed before the row is gone.
SCRATCHPAD_EXPIRY_GRACE_DAYS = 14
# Some keys are rewritten on every run, so revisions are capped per key as well as by age.
SCRATCHPAD_REVISION_RETENTION_DAYS = 14


def prune_expired_scratchpad_entries(grace_days: int = SCRATCHPAD_EXPIRY_GRACE_DAYS) -> int:
    """Hard-delete scratchpad rows whose `expires_at` passed more than `grace_days` ago.

    Cross-team janitor sweep. A durable entry (`expires_at` NULL) is the large majority of the
    store and is never touched — only a lapsed, time-boxed memory past its grace is removed.
    Returns the count deleted.
    """
    cutoff = timezone.now() - timedelta(days=grace_days)
    deleted, _ = (
        # nosemgrep: idor-lookup-without-team (system Celery janitor, no user input; unscoped is the sanctioned cross-team access)
        SignalScratchpad.objects.unscoped().filter(expires_at__isnull=False, expires_at__lt=cutoff).delete()
    )
    return deleted


def prune_scratchpad_revisions(
    retention_days: int = SCRATCHPAD_REVISION_RETENTION_DAYS, per_key: int = SCRATCHPAD_REVISIONS_PER_KEY
) -> int:
    """Hard-delete scratchpad revisions older than `retention_days`, and those past the newest `per_key` of a key.

    Cross-team janitor sweep, like `prune_expired_scratchpad_entries`. Returns the count deleted.
    """
    cutoff = timezone.now() - timedelta(days=retention_days)
    # nosemgrep: idor-lookup-without-team (system Celery janitor, no user input; unscoped is the sanctioned cross-team access)
    revisions = SignalScratchpadRevision.objects.unscoped()
    past_cap = (
        revisions.annotate(
            position=Window(
                RowNumber(),
                partition_by=[F("team_id"), F("key")],
                order_by=[F("changed_at").desc(), F("id").desc()],
            )
        )
        .filter(position__gt=per_key)
        .values("id")
    )
    deleted, _ = revisions.filter(Q(changed_at__lt=cutoff) | Q(id__in=past_cap)).delete()
    return deleted


@shared_task(
    name="products.signals.backend.tasks.prune_expired_scratchpad_entries",
    ignore_result=True,
    max_retries=0,
    soft_time_limit=110,
    time_limit=170,
)
@skip_team_scope_audit
def prune_expired_scratchpad_entries_task() -> None:
    """Daily janitor: hard-delete scratchpad entries long past their expiry, and old revisions.

    A scout that writes a time-boxed memory almost never comes back to `forget` it, so expired
    rows would otherwise pile up forever — expiry only hides a row from searches, it never removed
    one. Runs here rather than on the coordinator's 30-minute tick, which stays bounded.
    """
    deleted = 0
    revisions_deleted = 0
    try:
        deleted = prune_expired_scratchpad_entries()
        revisions_deleted = prune_scratchpad_revisions()
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        _report_scratchpad_janitor_error(exc, event_prefix="signals_scout.scratchpad_prune")
    logger.info("signals_scout scratchpad prune finished", deleted=deleted, revisions_deleted=revisions_deleted)


def _report_scratchpad_janitor_error(exc: Exception, *, event_prefix: str) -> None:
    if isinstance(exc, OperationalError):
        # A transient DB blip self-heals — the sweep runs again tomorrow — so don't page on it.
        logger.warning(f"{event_prefix}_transient_db_error", error=str(exc))
    elif is_stale_connection_read_only_error(exc):
        # The pooled connection outlived a primary failover. Drop it so the next run reconnects to the primary.
        connections.close_all()
        logger.warning(f"{event_prefix}_transient_db_error", error=str(exc))
    else:
        capture_exception(exc)
        logger.exception(f"{event_prefix}_failed")


# A `report:` entry must go this long without a write before the sweep judges it. A scout that
# rewrote its pointer recently still uses it, and a fresh pointer can name a report whose row
# is not committed yet.
REPORT_POINTER_MIN_AGE_DAYS = 30
REPORT_POINTER_SWEEP_BATCH_SIZE = 500
REPORT_POINTER_SWEEP_MAX_BATCHES = 20
# The sweep reads at most one capped slice per day, so it continues from this cursor on the next
# run. Without it, a store larger than the cap would scan the same head rows every day.
REPORT_POINTER_SWEEP_CURSOR_KEY = "signals:scratchpad:report_pointer_sweep_cursor"
_REPORT_POINTER_SWEEP_CURSOR_TTL_SECONDS = 7 * 24 * 60 * 60
_REPORT_ID_PATTERN = re.compile(UUID_REGEX, re.IGNORECASE)


@frozen
class ReportPointerSweep:
    scanned: int
    matched: int
    expired: int


def single_report_id(content: str) -> str | None:
    """The one report id a `report:` pointer names, or None when it names none or several.

    Scouts often write the same id twice (in a link and in backticks), so repeats collapse first.
    Several distinct ids make the pointer ambiguous, and the sweep must leave an ambiguous pointer alone.
    """
    ids = {match.lower() for match in _REPORT_ID_PATTERN.findall(content)}
    return ids.pop() if len(ids) == 1 else None


def _live_report_pointers(pointers: set[tuple[int, str]]) -> set[tuple[int, str]]:
    if not pointers:
        return set()
    # nosemgrep: idor-lookup-without-team (system Celery janitor, no user input; team_id__in plus the pair check below scope each id to its entry's team)
    live = SignalReport.objects.filter(
        team_id__in={team_id for team_id, _ in pointers},
        id__in={report_id for _, report_id in pointers},
    ).exclude(status=SignalReport.Status.DELETED)
    # The pair check keeps the lookup inside the entry's own team: a report id that exists only
    # in another team counts as missing.
    return {(team_id, str(report_id)) for team_id, report_id in live.values_list("team_id", "id")}


def expire_dangling_report_pointers(
    *,
    write: bool,
    batch_size: int = REPORT_POINTER_SWEEP_BATCH_SIZE,
    max_batches: int = REPORT_POINTER_SWEEP_MAX_BATCHES,
) -> ReportPointerSweep:
    """Expire durable `report:` scratchpad entries whose one report is missing or deleted.

    Cross-team sweep over at most `max_batches * batch_size` entries, which continues from where the
    previous run stopped. An entry qualifies only when it is older than `REPORT_POINTER_MIN_AGE_DAYS`
    and names exactly one report id. A live, resolved, closed or suppressed report keeps its pointer,
    because the pointer still tells the scout that the topic has history. With `write` off, the sweep
    counts what it would expire and changes nothing.

    The write sets `expires_at` through `QuerySet.update()`, so `content` and the `auto_now`
    `updated_at` stay as they are. Search orders by `updated_at`, and a bump would move the retired
    entries to the top. The expired entry then follows the normal path: hidden from search, readable
    with `include_expired`, and deleted by `prune_expired_scratchpad_entries` after the grace.
    Each expiry stores a revision under `REPORT_POINTER_SWEEP_IDENTITY`, as a `remember` would, so a
    scout that reads the expired key sees that the sweep retired it rather than the last scout to write it.
    """
    now = timezone.now()
    cutoff = now - timedelta(days=REPORT_POINTER_MIN_AGE_DAYS)
    # nosemgrep: idor-lookup-without-team (system Celery janitor, no user input; unscoped is the sanctioned cross-team access)
    eligible = SignalScratchpad.objects.unscoped().filter(
        key__startswith="report:", expires_at__isnull=True, updated_at__lt=cutoff
    )
    after = cache.get(REPORT_POINTER_SWEEP_CURSOR_KEY)
    scanned = matched = expired = 0
    for _ in range(max_batches):
        page = eligible.order_by("id")
        if after is not None:
            page = page.filter(id__gt=after)
        rows = list(page.values_list("id", "team_id", "content")[:batch_size])
        scanned += len(rows)

        pointers = {
            entry_id: (team_id, report_id)
            for entry_id, team_id, content in rows
            if (report_id := single_report_id(content)) is not None
        }
        live = _live_report_pointers(set(pointers.values()))
        dangling = [entry_id for entry_id, pointer in pointers.items() if pointer not in live]
        matched += len(dangling)
        if write and dangling:
            # Re-applies the eligibility filter, so an entry a scout rewrote since the read keeps its pointer.
            expired += _expire_report_pointers(eligible.filter(id__in=dangling), now=now)

        if len(rows) < batch_size:
            cache.delete(REPORT_POINTER_SWEEP_CURSOR_KEY)
            break
        after = str(rows[-1][0])
        cache.set(REPORT_POINTER_SWEEP_CURSOR_KEY, after, timeout=_REPORT_POINTER_SWEEP_CURSOR_TTL_SECONDS)
    return ReportPointerSweep(scanned=scanned, matched=matched, expired=expired)


def _expire_report_pointers(entries: QuerySet[SignalScratchpad], *, now: datetime) -> int:
    with transaction.atomic():
        # The row lock re-checks the filter against a concurrent `remember`, and keeps the revision and the
        # expiry in step: a write that lands first takes the entry out of the filter, and one that lands
        # after waits and then stores a revision of the expired state.
        locked = list(entries.select_for_update().only("id", "team_id", "key", "content", "expires_at").order_by("id"))
        if not locked:
            return 0
        # nosemgrep: idor-lookup-without-team (system Celery janitor, no user input; unscoped is the sanctioned cross-team access)
        SignalScratchpadRevision.objects.unscoped().bulk_create(
            SignalScratchpadRevision(
                team_id=entry.team_id,
                key=entry.key,
                content=entry.content,
                expires_at=entry.expires_at,
                change=SignalScratchpadRevision.Change.OVERWRITE,
                changed_by_identity=REPORT_POINTER_SWEEP_IDENTITY,
            )
            for entry in locked
        )
        # nosemgrep: idor-lookup-without-team (system Celery janitor, no user input; unscoped is the sanctioned cross-team access)
        return SignalScratchpad.objects.unscoped().filter(id__in=[entry.id for entry in locked]).update(expires_at=now)


@shared_task(
    name="products.signals.backend.tasks.expire_dangling_report_pointers",
    ignore_result=True,
    max_retries=0,
    soft_time_limit=110,
    time_limit=170,
)
@skip_team_scope_audit
def expire_dangling_report_pointers_task() -> None:
    """Daily sweep: retire `report:` scratchpad pointers whose report is gone.

    A durable pointer is never swept by the expiry janitor, and a scout rarely `forget`s one, so a
    pointer to a deleted report would stay in every wide scratchpad read forever.
    """
    write = settings.SIGNALS_EXPIRE_DANGLING_REPORT_POINTERS
    sweep = ReportPointerSweep(scanned=0, matched=0, expired=0)
    try:
        sweep = expire_dangling_report_pointers(write=write)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        _report_scratchpad_janitor_error(exc, event_prefix="signals_scout.report_pointer_sweep")
    logger.info(
        "signals_scout report pointer sweep finished",
        write_enabled=write,
        scanned=sweep.scanned,
        matched=sweep.matched,
        expired=sweep.expired,
    )


@shared_task(
    name="products.signals.backend.tasks.refresh_signal_repository_activity",
    ignore_result=True,
    max_retries=0,
    # The chain holds each countdown message in one worker's memory for the whole interval.
    # Ack it only after the batch schedules the next one, so a worker restart (deploy,
    # scale-down, OOM) redelivers the message and resumes the walk instead of dropping it.
    acks_late=True,
    reject_on_worker_lost=True,
)
@skip_team_scope_audit
def refresh_signal_repository_activity(after_team_id: int | None = None, after_repository: str | None = None) -> None:
    """Weekly (Monday) warm-up: enqueue a rebuild for every recently-used repository map.

    Releases rebuilds in batches of ``_REFRESH_BATCH_SIZE``. Each batch re-schedules the next
    after ``_REFRESH_BATCH_INTERVAL_SECONDS`` via a stable (team_id, repository) cursor, so the
    fan-out spreads over the window instead of bursting past Modal's sandbox-creation rate limit.
    """
    now = timezone.now()
    first_batch = after_team_id is None and after_repository is None
    if first_batch:
        SignalRepositoryAreaActivity.objects.unscoped().filter(
            last_used_at__lt=now - _ACTIVITY_ROW_MAX_IDLE
        ).delete()  # nosemgrep: idor-lookup-without-team (system Celery sweeper, no user input; unscoped is the sanctioned cross-team access)

    warm = SignalRepositoryAreaActivity.objects.unscoped().filter(  # nosemgrep: idor-lookup-without-team (system Celery sweeper, no user input; unscoped is the sanctioned cross-team access)
        last_used_at__gte=now - ACTIVITY_KEEP_WARM_WINDOW
    )
    if after_team_id is not None and after_repository is not None:
        warm = warm.filter(Q(team_id__gt=after_team_id) | Q(team_id=after_team_id, repository__gt=after_repository))
    batch = list(
        warm.values_list("team_id", "repository").distinct().order_by("team_id", "repository")[:_REFRESH_BATCH_SIZE]
    )
    if not batch:
        return
    for team_id, repository in batch:
        rebuild_signal_repository_activity.delay(team_id=team_id, repository=repository, force=True)
    logger.info("signals repository activity refresh enqueued rebuilds", count=len(batch))
    if len(batch) == _REFRESH_BATCH_SIZE:
        last_team_id, last_repository = batch[-1]
        refresh_signal_repository_activity.apply_async(
            kwargs={"after_team_id": last_team_id, "after_repository": last_repository},
            countdown=_REFRESH_BATCH_INTERVAL_SECONDS,
        )
