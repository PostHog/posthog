"""Celery tasks that keep a broadcast request and its Slack card in step with the pull request."""

from __future__ import annotations

from django.db import router

import structlog
from celery import Task, shared_task

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError

from products.stamphog.backend.facade.enums import ACTIVE_BROADCAST_REQUEST_STATUSES, ReviewRunStatus
from products.stamphog.backend.logic import broadcast_links, broadcast_requests
from products.stamphog.backend.logic.broadcast_requests import LinkAskOutcome
from products.stamphog.backend.models import BroadcastRequest, ReviewRun

logger = structlog.get_logger(__name__)

_MAX_RETRIES = 5
_RETRY_BASE_SECONDS = 30
# The outcomes whose request belongs to the post, so its card is due in the post's thread.
_OPENED_BY_THIS_POST = frozenset({LinkAskOutcome.CREATED, LinkAskOutcome.REPEATED})


@shared_task(bind=True, ignore_result=True, max_retries=_MAX_RETRIES)
def refresh_broadcast_request(self: Task, team_id: int, broadcast_request_id: str, decided_head_sha: str = "") -> None:
    """Recompute one Broadcast request from the database and GitHub, then post or edit its Slack card.

    Every change to a request goes through this task, so it must be idempotent: a retry or a second
    queue for the same state posts nothing new. GitHub and Slack errors retry with backoff.
    ``decided_head_sha`` is described in ``broadcast_requests.refresh``.
    """
    try:
        broadcast_requests.refresh(team_id, broadcast_request_id, decided_head_sha=decided_head_sha)
    except (GitHubRateLimitError, GitHubEgressBudgetExhausted) as e:
        raise self.retry(exc=e, countdown=max(getattr(e, "retry_after", None) or 0, 60))
    except Exception as e:
        logger.exception("stamphog_broadcast_request_refresh_failed", broadcast_request_id=broadcast_request_id)
        raise self.retry(exc=e, countdown=_RETRY_BASE_SECONDS * 2**self.request.retries)


def queue_broadcast_request_refresh(team_id: int, broadcast_request_id: str, *, decided_head_sha: str = "") -> None:
    """Queue ``refresh_broadcast_request``. Never raises, because the caller's own write already committed."""
    try:
        refresh_broadcast_request.delay(
            team_id=team_id, broadcast_request_id=broadcast_request_id, decided_head_sha=decided_head_sha
        )
    except Exception:
        logger.exception("stamphog_broadcast_request_refresh_queue_failed", broadcast_request_id=broadcast_request_id)


@shared_task(bind=True, ignore_result=True, max_retries=_MAX_RETRIES)
def refresh_broadcast_requests_for_pull_request(
    self: Task, repository: str, pr_number: int, installation_id: str = "", decided_head_sha: str = ""
) -> None:
    """Refresh every active Broadcast request of one pull request, in every team that has one.

    A GitHub delivery only says that something changed, so each refresh reads the state from GitHub
    itself. The PostHog App's installation is not stamphog's, so a delivery from it passes no
    ``installation_id`` and matches on the repository and number alone. Only the review path sets
    ``decided_head_sha``, to the head it decided. A database error retries with backoff, because
    ingress already acknowledged the delivery.
    """
    requests = BroadcastRequest.objects.unscoped().using(router.db_for_write(BroadcastRequest))
    requests = requests.filter(
        pull_request__repo_config__repository=repository,
        pull_request__pr_number=pr_number,
        status__in=ACTIVE_BROADCAST_REQUEST_STATUSES,
    )
    if installation_id:
        requests = requests.filter(pull_request__repo_config__installation_id=installation_id)
    try:
        targets = list(requests.values_list("team_id", "id"))
    except Exception as e:
        logger.exception("stamphog_broadcast_requests_enumeration_failed", repo=repository, pr_number=pr_number)
        raise self.retry(exc=e, countdown=_RETRY_BASE_SECONDS * 2**self.request.retries)
    for team_id, request_id in targets:
        queue_broadcast_request_refresh(team_id, str(request_id), decided_head_sha=decided_head_sha)


def queue_broadcast_request_refresh_after_verdict(run: ReviewRun, status: ReviewRunStatus) -> None:
    """Refresh the pull request's active Broadcast request once a run's outcome reached GitHub. Never raises.

    A verdict that a silent run withheld queues nothing, so the card never shows an outcome that
    GitHub does not have.
    """
    try:
        published = run.may_publish() if status == ReviewRunStatus.FAILED else run.verdict_posted_at is not None
        if not published:
            return
        request_ids = (
            BroadcastRequest.objects.for_team(run.team_id)
            .using(router.db_for_write(BroadcastRequest))
            .filter(pull_request_id=run.pull_request_id, status__in=ACTIVE_BROADCAST_REQUEST_STATUSES)
            .values_list("id", flat=True)
        )
        for request_id in request_ids:
            queue_broadcast_request_refresh(run.team_id, str(request_id))
    except Exception:
        logger.exception("stamphog_broadcast_request_queue_after_verdict_failed", review_run_id=str(run.id))


@shared_task(bind=True, ignore_result=True, max_retries=_MAX_RETRIES)
def open_broadcast_request_from_link(
    self: Task,
    slack_team_id: str,
    channel_id: str,
    message_ts: str,
    slack_user_id: str,
    repository: str,
    pr_number: int,
    user_ids: list[int],
    link_count: int = 1,
) -> None:
    """Open the Broadcast request for a pull request link that a person posted in a Broadcast channel.

    A retry for the same post finds the request it opened, so it posts no second card. GitHub errors
    retry with backoff.
    """
    post = broadcast_links.LinkPost(
        slack_team_id=slack_team_id,
        channel_id=channel_id,
        message_ts=message_ts,
        slack_user_id=slack_user_id,
        link=broadcast_links.PullRequestLink(repository=repository, pr_number=pr_number),
        link_count=link_count,
        user_ids=tuple(user_ids),
    )
    try:
        asked = broadcast_links.open_from_link(post)
    except (GitHubRateLimitError, GitHubEgressBudgetExhausted) as e:
        raise self.retry(exc=e, countdown=max(getattr(e, "retry_after", None) or 0, 60))
    except Exception as e:
        logger.exception("stamphog_broadcast_link_failed", slack_channel_id=channel_id, message_ts=message_ts)
        raise self.retry(exc=e, countdown=_RETRY_BASE_SECONDS * 2**self.request.retries)
    if asked is not None and asked.request is not None and asked.outcome in _OPENED_BY_THIS_POST:
        # Posted here rather than queued, so a failure retries this task. A retry finds its own request.
        try:
            broadcast_requests.refresh(asked.request.team_id, str(asked.request.id))
        except Exception as e:
            logger.exception("stamphog_broadcast_link_card_failed", slack_channel_id=channel_id)
            raise self.retry(exc=e, countdown=_RETRY_BASE_SECONDS * 2**self.request.retries)


def queue_open_broadcast_request_from_link(post: broadcast_links.LinkPost) -> None:
    """Queue ``open_broadcast_request_from_link``. Never raises, because it runs inside Slack's event request."""
    try:
        open_broadcast_request_from_link.delay(
            slack_team_id=post.slack_team_id,
            channel_id=post.channel_id,
            message_ts=post.message_ts,
            slack_user_id=post.slack_user_id,
            repository=post.link.repository,
            pr_number=post.link.pr_number,
            user_ids=list(post.user_ids),
            link_count=post.link_count,
        )
    except Exception:
        logger.exception("stamphog_broadcast_link_queue_failed", slack_channel_id=post.channel_id)
