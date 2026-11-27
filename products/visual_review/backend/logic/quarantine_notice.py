"""Tell the team that owns a story, in its Slack channel, that somebody just quarantined it.

The person who quarantines asks for this, so the owning team hears about it at once instead of in
the weekly debt digest. It reuses the digest's pieces: the same owner lookup, the same channel, and
the same rendering of a quarantine. A story no team owns gets no notice, because the message says
"owned by you" and the maintainers already see unowned items in the digest.

People quarantine several snapshots in a row, one dialog at a time, and an automatic job can
quarantine many stories at once. A post per quarantine floods the team's channel, so notices for one
repo wait until the quarantines stop coming in. Each quarantine marks its row pending and queues a
delayed task. A task that runs while the newest pending row is still inside the quiet window does
nothing, because that row's own task runs later. The first task to run after the window posts every
pending row, one message per owning team and author.

Best effort. A quarantine never fails because its notice could not be sent, and nothing retries a
notice.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.ownership.github_files import fetcher_for_team
from posthog.ownership.paths import UNOWNED_TEAM, resolve_path_owners
from posthog.slack.channels import MAX_BLOCKS, clip_text, section_block
from posthog.slack.formatting import escape_slack_mrkdwn

from ..db import WRITER_DB
from ..facade.contracts import AUTO_EXTEND_REASON_PREFIX
from ..facade.enums import ActorType
from ..models import QuarantinedIdentifier, Repo
from . import owners, run_queries, story_index, team_channels
from .debt_digest import PRODUCT_PATH, display_names, quarantine_facts, snapshot_button
from .run_queries import SnapshotKey
from .team_channels import SlackMessage

logger = structlog.get_logger(__name__)

_MAX_IDENTIFIER_CHARS = 160
# A steady stream of quarantines always leaves a newer row, so without this limit the first notice
# of the stream would wait until the stream stops.
_MAX_HOLD = timedelta(minutes=10)
# A pending row this old lost its own task, for example to the queue expiry. A later task takes it
# off the queue but does not post it, because it no longer reports something that just happened.
_STALE_AFTER = timedelta(minutes=30)
# Celery and the web pod read different clocks. Without this margin, the newest row's own task could
# run a moment before its window ends by the database's timestamps, and leave the burst unposted.
_CLOCK_SLACK = timedelta(seconds=30)
_MAX_STORIES_PER_MESSAGE = (MAX_BLOCKS - 2) // 2


@frozen
class NoticeRun:
    """What one notice task did: the posts it made, and when to look again if the burst is still open."""

    posts: int
    recheck_in_seconds: int | None = None


@frozen
class _Audience:
    """Who reads one post, and whose action it reports. Quarantines with the same audience share a post."""

    team_slug: str
    source: str
    auto_extension: bool
    created_by_id: int | None


@frozen
class _Story:
    entry: QuarantinedIdentifier
    source_path: str


@frozen
class _Claim:
    entries: list[QuarantinedIdentifier]
    recheck_in_seconds: int | None


def _is_auto_extension(entry: QuarantinedIdentifier) -> bool:
    return entry.source == ActorType.AUTO and entry.reason.startswith(AUTO_EXTEND_REASON_PREFIX)


def _lead(entry: QuarantinedIdentifier, actor: str, story_count: int) -> str:
    one = story_count == 1
    stories = "a story" if one else f"{story_count} stories"
    if _is_auto_extension(entry):
        still_renders = "the story still renders" if one else "the stories still render"
        return (
            f"*Visual review* extended the quarantine of {stories} owned by you automatically, "
            f"because {still_renders} differently on the default branch. Please check."
        )
    if entry.source == ActorType.AUTO:
        rendered = "it" if one else "each of them"
        return (
            f"*Visual review* quarantined {stories} owned by you automatically, "
            f"because the same code rendered {rendered} two ways. Please check."
        )
    by = f"{actor} (using an AI agent)" if entry.source == ActorType.AGENT else actor
    return f"*{escape_slack_mrkdwn(by)}* quarantined {stories} owned by you. Please check."


def _story_name(entry: QuarantinedIdentifier) -> str:
    # The story without its theme: one line covers every theme variant quarantined with it.
    return story_index.split_theme(entry.identifier).rest


def _plain_context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "plain_text", "text": clip_text(text, 2000), "emoji": False}]}


def build_message(repo: Repo, stories: list[_Story], actor: str) -> SlackMessage:
    lead = _lead(stories[0].entry, actor, len(stories))
    now = timezone.now()
    blocks = [section_block(lead)]
    for story in stories[:_MAX_STORIES_PER_MESSAGE]:
        entry = story.entry
        name = escape_slack_mrkdwn(clip_text(_story_name(entry), _MAX_IDENTIFIER_CHARS))
        facts = quarantine_facts(entry, {entry.created_by_id or 0: actor}, now)
        blocks.append(
            section_block(
                f"*{name}* {escape_slack_mrkdwn(entry.run_type)}\n{facts}",
                snapshot_button(repo, entry.run_type, entry.identifier, "Open snapshot"),
            )
        )
        # The path comes from the repository, so it renders as plain text: in mrkdwn a backtick in it
        # would close the code span and let Slack auto-link whatever follows.
        blocks.append(_plain_context(f"{repo.repo_full_name} · {story.source_path}"))
    left_out = len(stories) - _MAX_STORIES_PER_MESSAGE
    if left_out > 0:
        blocks.append(_plain_context(f"{left_out} more not shown."))
    first_name = escape_slack_mrkdwn(clip_text(_story_name(stories[0].entry), _MAX_IDENTIFIER_CHARS))
    return SlackMessage(blocks=blocks, text=f"{lead} {first_name}" if len(stories) == 1 else lead)


def _still_news(entry: QuarantinedIdentifier, now: datetime) -> bool:
    if entry.expires_at is not None and entry.expires_at <= now:
        return False
    return entry.created_at > now - _STALE_AFTER


def _clear_pending(entries: list[QuarantinedIdentifier], team_id: int) -> None:
    QuarantinedIdentifier.objects.using(WRITER_DB).filter(
        team_id=team_id, id__in=[entry.id for entry in entries]
    ).update(owner_notice_pending=False)


def _claim_pending(trigger_id: UUID, team_id: int) -> _Claim:
    """Take the repo's pending rows off the queue, or none while the burst is still open.

    The claim commits before anything posts, so a post that fails is not retried by a later task.
    """
    from ..tasks.tasks import QUARANTINE_NOTICE_QUIET_SECONDS  # noqa: PLC0415 — avoids the logic/tasks circular import

    repo_id = (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(id=trigger_id, team_id=team_id)
        .values_list("repo_id", flat=True)
        .first()
    )
    if repo_id is None:
        return _Claim(entries=[], recheck_in_seconds=None)
    now = timezone.now()
    with transaction.atomic(using=WRITER_DB):
        # One notice task at a time per repo. Two tasks that both see the burst as over would otherwise
        # claim different rows and post the same burst to the same team twice.
        # NO KEY: a quarantine insert takes KEY SHARE on the repo for its foreign key, and FOR UPDATE
        # would block it while this transaction waits on that quarantine's rows.
        Repo.objects.using(WRITER_DB).select_for_update(no_key=True).filter(id=repo_id, team_id=team_id).first()
        pending = list(
            QuarantinedIdentifier.objects.using(WRITER_DB)
            .filter(repo_id=repo_id, team_id=team_id, owner_notice_pending=True)
            .select_related("repo")
            .order_by("created_at")
        )
        news: list[QuarantinedIdentifier] = []
        stale: list[QuarantinedIdentifier] = []
        for entry in pending:
            if _still_news(entry, now):
                news.append(entry)
            else:
                stale.append(entry)
        if news:
            quiet_until = news[-1].created_at + timedelta(seconds=QUARANTINE_NOTICE_QUIET_SECONDS)
            waited_long_enough = news[0].created_at <= now - _MAX_HOLD
            if now < quiet_until - _CLOCK_SLACK and not waited_long_enough:
                _clear_pending(stale, team_id)
                # The oldest row's task looks again after the newest row's task should have posted.
                # That covers a newest-row task that the broker lost or that expired in the queue.
                if news[0].id != trigger_id:
                    return _Claim(entries=[], recheck_in_seconds=None)
                return _Claim(entries=[], recheck_in_seconds=int((quiet_until + _CLOCK_SLACK - now).total_seconds()))
        _clear_pending(pending, team_id)
    return _Claim(entries=news, recheck_in_seconds=None)


def send_pending_notices(trigger_id: UUID, team_id: int) -> NoticeRun:
    """Post the repo's pending quarantines once the burst is over, one message per owning team and author."""
    claim = _claim_pending(trigger_id, team_id)
    entries = claim.entries
    if not entries:
        logger.info("visual_review.quarantine_notice_nothing_to_send", trigger_id=str(trigger_id), team_id=team_id)
        return NoticeRun(posts=0, recheck_in_seconds=claim.recheck_in_seconds)
    repo = entries[0].repo

    keys = [SnapshotKey(run_type=entry.run_type, identifier=entry.identifier) for entry in entries]
    found = owners.snapshot_owners(
        repo, keys, run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo.id))
    )
    stories_by_audience: dict[_Audience, list[_Story]] = defaultdict(list)
    seen_stories: set[tuple[_Audience, str, str, str, date | None]] = set()
    for entry, key in zip(entries, keys):
        team_slug = found.team_by_key.get(key)
        if team_slug is None or team_slug == UNOWNED_TEAM:
            logger.info("visual_review.quarantine_notice_no_owner", entry_id=str(entry.id), team_id=team_id)
            continue
        audience = _Audience(
            team_slug=team_slug,
            source=entry.source,
            auto_extension=_is_auto_extension(entry),
            created_by_id=entry.created_by_id,
        )
        # The post names the expiry by day, so variants whose expiries differ by seconds read the same.
        expiry_day = entry.expires_at.date() if entry.expires_at is not None else None
        story = (audience, entry.run_type, _story_name(entry), entry.reason, expiry_day)
        if story in seen_stories:
            continue
        seen_stories.add(story)
        stories_by_audience[audience].append(_Story(entry=entry, source_path=found.path_by_key[key]))
    if not stories_by_audience:
        return NoticeRun(posts=0)

    workspace = team_channels.open_workspace(repo.team_id)
    if workspace is None:
        return NoticeRun(posts=0)
    actors = display_names({audience.created_by_id for audience in stories_by_audience if audience.created_by_id})
    posts = 0
    for audience, stories in stories_by_audience.items():
        actor = actors.get(audience.created_by_id or 0, "Someone")
        message = build_message(repo, stories, actor)
        try:
            posted = team_channels.post_to_team(workspace, audience.team_slug, found.registry, message)
        except Exception:
            # The claim already cleared every row of the batch, so one team's broken channel must not
            # cost the other teams their posts.
            logger.warning("visual_review.quarantine_notice_post_failed", team_slug=audience.team_slug, exc_info=True)
            continue
        logger.info(
            "visual_review.quarantine_notice", team_slug=audience.team_slug, stories=len(stories), posted=posted
        )
        posts += int(posted)
    return NoticeRun(posts=posts)


def daily_limit_message(repo: Repo, automatic_count: int) -> SlackMessage:
    lead = (
        f"Visual review quarantined {automatic_count} stories automatically in {escape_slack_mrkdwn(repo.repo_full_name)} "
        "in the last 24 hours. The capture harness may have regressed. "
        "Further flake proofs are logged and not applied until the count drops."
    )
    return SlackMessage(blocks=[section_block(lead)], text=lead)


def send_daily_limit_notice(repo_id: UUID, team_id: int, automatic_count: int) -> bool:
    """Tell whoever owns visual review that the daily limit stopped automatic quarantines.

    Routed like the digest's items that no team owns. False when nothing was posted.
    """
    repo = Repo.objects.filter(id=repo_id, team_id=team_id).first()
    if repo is None:
        return False
    ownership = resolve_path_owners(
        repo.repo_full_name,
        [PRODUCT_PATH],
        files=fetcher_for_team(repo.team_id, repo.repo_full_name, priority=Priority.BATCH),
    )
    team_slug = ownership.team_by_path.get(PRODUCT_PATH)
    if not ownership.resolved or team_slug is None or team_slug == UNOWNED_TEAM:
        logger.info("visual_review.auto_quarantine_limit_notice_no_owner", repo_id=str(repo_id))
        return False
    workspace = team_channels.open_workspace(repo.team_id)
    if workspace is None:
        return False
    posted = team_channels.post_to_team(
        workspace, team_slug, ownership.registry, daily_limit_message(repo, automatic_count)
    )
    logger.info("visual_review.auto_quarantine_limit_notice", repo_id=str(repo_id), team_slug=team_slug, posted=posted)
    return posted
