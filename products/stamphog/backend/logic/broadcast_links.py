"""Broadcast requests that a person opens by posting a pull request link in a Broadcast channel.

The person asks teammates directly, often because the pull request is too big for stamphog, so no review
starts. The request opens at once, and its card goes into the thread of the post. After that it follows
the pull request like every other Broadcast request (``logic/broadcast_requests.py``).

Every drop here is silent: a link nobody may ask about, or one in a channel that is not a Broadcast
channel, gets no answer, so the bot tells nobody which repositories it knows.
"""

from __future__ import annotations

import re

from django.core.cache import cache
from django.db import router, transaction
from django.db.models import QuerySet

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.github.requesters import Requester, members_with_resource_access, resolve_requester
from posthog.integrations import IntegrationManager
from posthog.models import Team, User
from posthog.token_bucket import BucketDecision, Budget, consume

from ..facade.enums import BroadcastRequestSource
from ..models import BroadcastRequest, PullRequest, StamphogRepoConfig
from .broadcast_request_slack import card_workspace, find_card_integration, post_thread_reply
from .broadcast_requests import (
    BroadcastRequestAsk,
    LinkAsk,
    LinkAskOutcome,
    earlier_link_ask,
    human_approver,
    open_link_request,
    stamphog_approval_live,
)
from .github_client import StamphogGitHubClient, StamphogGitHubError
from .installations import reviewable_repo_configs

logger = structlog.get_logger(__name__)

# The owner and repository name rules of GitHub.
_PULL_REQUEST_LINK = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100})/pull/(\d{1,9})\b",
    re.IGNORECASE,
)
# Short, because a manager who turns Broadcast on for a channel expects the next link to work. The task
# reads the config again from the writer, so a stale entry never posts on its own.
_CHANNEL_CACHE_SECONDS = 60
# Several links in one post each get a card, up to this many, so one post cannot fill a thread.
MAX_LINKS_PER_POST = 5
# Longer than Slack retries a delivery, and long enough for the copy that the other region forwards.
_CLAIM_SECONDS = 60 * 60

ALREADY_ASKED_WITH_LINK = "Already asked here: <{permalink}>"
ALREADY_ASKED = "Someone already asked for reviews on this pull request."
ALREADY_APPROVED = "Already approved by {login}."
STAMPHOG_ALREADY_APPROVED = "Stamphog already approved this pull request."


@frozen
class PullRequestLink:
    repository: str
    pr_number: int


@frozen
class LinkPost:
    """A top-level post with a pull request link, in a channel that is a Broadcast channel."""

    slack_team_id: str
    channel_id: str
    message_ts: str
    slack_user_id: str
    link: PullRequestLink
    # How many links of the post are handled. With more than one, each thread reply names its pull request.
    link_count: int
    # The PostHog accounts of the person who posted, the one the Slack app resolved for them first.
    user_ids: tuple[int, ...]


@frozen
class _LinkTarget:
    repo_config: StamphogRepoConfig
    user_id: int
    integration_id: int


def pull_request_links(text: str) -> tuple[PullRequestLink, ...]:
    """The distinct pull request links in ``text``, in order, at most ``MAX_LINKS_PER_POST``."""
    links: list[PullRequestLink] = []
    seen: set[tuple[str, int]] = set()
    for match in _PULL_REQUEST_LINK.finditer(text):
        link = PullRequestLink(repository=match.group(1), pr_number=int(match.group(2)))
        key = (link.repository.lower(), link.pr_number)
        if key in seen:
            continue
        seen.add(key)
        links.append(link)
        if len(links) == MAX_LINKS_PER_POST:
            break
    return tuple(links)


def _workspace_project_ids(slack_team_id: str) -> set[int]:
    """The projects in this region whose Slack connection is the workspace. Repo configs live on the project."""
    team_ids = {row.team_id for row in IntegrationManager.slack.oauth.list_by_external_id(slack_team_id)}
    if not team_ids:
        return set()
    rows = Team.objects.filter(id__in=team_ids).values_list("id", "parent_team_id")
    return {parent_team_id or team_id for team_id, parent_team_id in rows}


def _broadcast_configs(slack_team_id: str, channel_id: str) -> QuerySet[StamphogRepoConfig]:
    return StamphogRepoConfig.objects.unscoped().filter(
        team_id__in=_workspace_project_ids(slack_team_id),
        enabled=True,
        broadcast_enabled=True,
        broadcast_slack_channel_id=channel_id,
    )


def broadcast_channel_repositories(slack_team_id: str, channel_id: str) -> frozenset[str]:
    """The repositories, in lowercase, that use ``channel_id`` as their Broadcast channel in a project of this region.

    Cached, because every pull request link in every channel that the app is in asks.
    """
    key = f"stamphog:broadcast_channel:{slack_team_id}:{channel_id}"
    cached = cache.get(key)
    if cached is not None:
        return frozenset(cached)
    repositories = sorted(
        {
            repository.lower()
            for repository in _broadcast_configs(slack_team_id, channel_id).values_list("repository", flat=True)
        }
    )
    cache.set(key, repositories, timeout=_CHANNEL_CACHE_SECONDS)
    return frozenset(repositories)


# The budget of the commands product for one person, so a link post costs a poster what a ``stamp`` does.
# Above it, posts are dropped silently, so a loop of reposts cannot fill the task queue or the GitHub budget.
_POSTER_BUDGET = Budget(burst=5, per_hour=30)


def poster_budget_key(slack_team_id: str, slack_user_id: str) -> str:
    return f"stamphog:broadcast_link_poster:{slack_team_id}:{slack_user_id}"


def poster_within_limit(slack_team_id: str, slack_user_id: str) -> bool:
    """Whether this poster may have another link post taken. True when Redis cannot answer."""
    decision = consume(poster_budget_key(slack_team_id, slack_user_id), _POSTER_BUDGET)
    return not isinstance(decision, BucketDecision) or decision.allowed


def claim_link_post(slack_team_id: str, channel_id: str, message_ts: str) -> bool:
    """Whether this call is the first for the post.

    Slack delivers a post again when the first answer is slow, and a region can receive a post both from
    Slack and from the other region. True when the cache cannot answer, because the unique active request
    still stops a second card.
    """
    try:
        return bool(
            cache.add(f"stamphog:broadcast_link:{slack_team_id}:{channel_id}:{message_ts}", True, _CLAIM_SECONDS)
        )
    except Exception:
        logger.warning("stamphog_broadcast_link_claim_failed", exc_info=True)
        return True


def _link_target(post: LinkPost) -> _LinkTarget | None:
    """The repo config that the link asks about, and the account that asks, or None when nobody may ask.

    The poster must be a member of the config's project with the access that a Slack ``stamp`` needs, the
    same check the commands product runs. The card must also go out through a Slack connection of the
    workspace that the post is in.
    """
    # Writer-pinned inside reviewable_repo_configs, because the cached channel check may be stale.
    configs = reviewable_repo_configs(
        _broadcast_configs(post.slack_team_id, post.channel_id), post.link.repository
    ).order_by("created_at", "id")
    by_id = User.objects.in_bulk(post.user_ids)
    users = [by_id[user_id] for user_id in post.user_ids if user_id in by_id and by_id[user_id].is_active]
    for repo_config in configs:
        requester = resolve_requester(users, [repo_config.team_id], call_site="stamphog_broadcast_link")
        if not isinstance(requester, Requester):
            return None
        members = members_with_resource_access(
            requester.members, users, resource="code_review_approval", level="editor"
        )
        if not members:
            continue
        integration_id = find_card_integration(repo_config.team_id)
        if integration_id is None or card_workspace(repo_config.team_id, integration_id) != post.slack_team_id:
            continue
        return _LinkTarget(repo_config=repo_config, user_id=members[0].user_id, integration_id=integration_id)
    return None


def _pull_request_row(repo_config: StamphogRepoConfig, pr: dict, *, using: str) -> PullRequest:
    pull_request, _ = (
        PullRequest.objects.for_team(repo_config.team_id)
        .using(using)
        .get_or_create(
            repo_config=repo_config,
            pr_number=pr["number"],
            defaults={
                "team_id": repo_config.team_id,
                "title": (pr.get("title") or "")[:512],
                "author_login": ((pr.get("user") or {}).get("login") or "")[:255],
                "pr_url": pr.get("html_url") or "",
                "head_branch": (pr.get("head") or {}).get("ref") or "",
            },
        )
    )
    return pull_request


def _reply(post: LinkPost, target: _LinkTarget, text: str) -> None:
    if post.link_count > 1:
        text = f"{post.link.repository}#{post.link.pr_number}: {text}"
    post_thread_reply(target.repo_config.team_id, target.integration_id, post.channel_id, post.message_ts, text)


def open_from_link(post: LinkPost) -> LinkAsk | None:
    """Open the Broadcast request that a posted link asks for, or answer in the post's thread why not.

    Returns None when the post gets nothing. The caller refreshes a request this created, which posts its card.
    Raises on a GitHub error, so the task retries.
    """
    target = _link_target(post)
    if target is None:
        logger.info("stamphog_broadcast_link_ignored", slack_channel_id=post.channel_id)
        return None
    repo_config = target.repo_config
    db = router.db_for_write(BroadcastRequest)
    # Before GitHub, so a link that people post again and again costs the installation no API calls.
    earlier = earlier_link_ask(
        repo_config.team_id,
        repo_config_id=repo_config.id,
        pr_number=post.link.pr_number,
        channel_id=post.channel_id,
        thread_ts=post.message_ts,
        using=db,
    )
    if earlier is not None:
        return _answer(post, target, earlier)
    client = StamphogGitHubClient(repo_config.installation_id, lane=Priority.NORMAL)
    try:
        pr = client.get_pr(repo_config.repository, post.link.pr_number)
    except StamphogGitHubError as e:
        if e.status_code == 404:
            return None
        raise
    if pr.get("state") != "open":
        return None
    reviews = client.get_pr_reviews(repo_config.repository, post.link.pr_number)
    approver = human_approver(reviews, pr["head"]["sha"], (pr.get("user") or {}).get("login") or "")
    if approver:
        _reply(post, target, ALREADY_APPROVED.format(login=approver))
        return None
    ask = BroadcastRequestAsk(
        requested_by_user_id=target.user_id,
        requested_via=BroadcastRequestSource.SLACK_LINK,
        requester_slack_user_id=post.slack_user_id,
    )
    with transaction.atomic(using=db):
        pull_request = _pull_request_row(repo_config, pr, using=db)
        asked = open_link_request(
            pull_request,
            pr["head"]["sha"],
            ask,
            channel_id=post.channel_id,
            thread_ts=post.message_ts,
            # Only an approval that GitHub shows answers a teammate's ask, so an unknown answer opens the request.
            stamphog_approval_live=stamphog_approval_live(reviews) is True,
            using=db,
        )
    return _answer(post, target, asked)


def _answer(post: LinkPost, target: _LinkTarget, asked: LinkAsk) -> LinkAsk:
    """Reply in the post's thread when the post opened no request. A request it opened gets its card later."""
    if asked.outcome == LinkAskOutcome.ALREADY_ASKED:
        text = ALREADY_ASKED_WITH_LINK.format(permalink=asked.permalink) if asked.permalink else ALREADY_ASKED
    elif asked.outcome == LinkAskOutcome.STAMPHOG_APPROVED:
        text = STAMPHOG_ALREADY_APPROVED
    else:
        return asked
    _reply(post, target, text)
    return asked
