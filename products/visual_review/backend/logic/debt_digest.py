"""The weekly reminder about visual review debt a team is still carrying.

Stateless by design. Every Monday the two conditions below are evaluated from current data,
attributed to the team that owns the file the snapshot's story lives in today, and posted. Nothing
is stored about what was sent, so an item repeats every week until the condition stops holding and
disappears the moment it does. A team whose post fails is logged and the run moves on; next Monday
recomputes everything from scratch.

The two conditions:

  Quarantine expiring. An active quarantine that runs out inside `FLAKINESS_EXPIRY_SOON_DAYS`, plus
  a day of overlap so two weekly runs cannot skip one. Somebody has to extend it, lift it, or decide
  to let it lapse.

  Variant pile-up. `VARIANT_PILEUP_MIN` or more accepted variants standing against the baseline's
  current hash, with no quarantine already covering the identity. The baseline has stopped
  describing one rendering.

A baseline change clears the second condition, and that is not the same as the story recovering: it
invalidates the tolerations recorded against the old baseline, because they can never match again.
Nothing here claims a snapshot got better.

Attribution runs through the Storybook build behind the current baseline. Its story index names the
file each story lives in, and the repository's own ownership files name the team that owns that file.
Three things stop that: no owners entry covers the file, the index has no such story, or there is no
index to read. All three go to the visual review maintainers, in a message of their own rather than
inside the digest those maintainers get for what they own, because holding an item until a team
takes it is not owning it.

The CLI uploads that story index with the run that built it, named by its content hash, so the
digest reads the index of the newest default-branch Storybook run and needs nothing else from CI.

Every message is Block Kit: a lead naming the team and the counts, then one thread reply per
condition, with the one action that resolves an item on a button beside it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

import structlog
from posthog_owners.resolver import Purpose, team_channel
from posthog_owners.schema import Producer, TeamEntry

from posthog.comment.formatting import escape_slack_mrkdwn
from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.team_notifications.slack import (
    MAX_BLOCKS,
    MAX_BUTTON_URL_CHARS,
    MAX_SECTION_CHARS,
    MAX_TEXT_CHARS,
    SlackButton,
    SlackChannel,
    SlackPostRefused,
    actions_block,
    clip_text,
    context_block,
    divider_block,
    fetch_channel_map,
    fields_block,
    find_channel,
    header_block,
    post_message,
    post_with_join,
    section_block,
)
from posthog.utils import human_list, pluralize

from products.engineering_analytics.backend.facade.api import resolve_path_owners
from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM, PathOwnership

from ..facade.contracts import FLAKINESS_EXPIRY_SOON_DAYS, VARIANT_PILEUP_MIN
from ..facade.enums import RunType
from ..models import QuarantinedIdentifier, Repo, Run
from . import quarantine, run_queries, story_index, toleration

logger = structlog.get_logger(__name__)

# The digest is automation, so it asks the registry where automation posts rather than where the
# team's people are. That falls back to the people channel when a team never separates the two.
_CHANNEL_PURPOSE: Purpose = "notifications"
# Named so a team can keep this digest out of its channel while other bots keep posting there.
_PRODUCER: Producer = "visual_review"

# Whose digest carries the items no team owns. The people who built the product can read a story
# name and find who to ask; nobody else can. Routed like any other team, so there is no second
# delivery path to keep working.
_PRODUCT_PATH = "products/visual_review/"


_MAX_LINE_CHARS = MAX_SECTION_CHARS // 2
# The full identifier still goes into the URL, so a cut display costs the reader nothing.
_MAX_IDENTIFIER_CHARS = 160
_MAX_REASON_CHARS = 200

# Slack takes 50 blocks in one message. One chunk size is used everywhere, so it keeps room for the
# heading every message repeats, the divider and context that close the last one, and the header and
# context a top-level message opens with.
_ITEMS_PER_MESSAGE = MAX_BLOCKS - 5

MODE_PREVIEW = "preview"
MODE_LIVE = "live"
MODES = (MODE_PREVIEW, MODE_LIVE)

# One day wider than the window the flakiness page uses. Two weekly runs can fall slightly more than
# seven days apart, and without the overlap a quarantine expiring in that gap is never reported.
_DIGEST_EXPIRY_WINDOW_DAYS = FLAKINESS_EXPIRY_SOON_DAYS + 1

_LEAD_BODY = "Each item and its action is in the thread."
_LEAD_LAPSE_NOTE = "Quarantines that lapse start failing the gate again on the next run."
_QUARANTINE_HEADING = (
    "*Quarantines expiring soon*\n"
    "Fix the story and let the quarantine lapse, or extend it with a new reason. "
    "A lapsed quarantine fails the gate again."
)
_PILEUP_HEADING = (
    "*Snapshots with piled-up variants*\n"
    f"{VARIANT_PILEUP_MIN} or more accepted renderings mean the baseline is wrong. "
    "Approve the current rendering as the baseline and the variants stop counting."
)


class AttributionKind(StrEnum):
    """What the story index can say about the file behind one snapshot."""

    PLACED = "placed"  # the story maps to a file in the repository
    STORY_ABSENT = "story_absent"  # the index was read, and it holds no such story
    UNAVAILABLE = "unavailable"  # there is no index to ask for this run type today


# Each outcome asks the reader for a different fix. A placed path here is one no owners entry covers.
# UNAVAILABLE is missing on purpose: it asks the reader for nothing, so it is counted, not listed.
_TRIAGE_HEADINGS: dict[AttributionKind, str] = {
    AttributionKind.PLACED: "*The file has no owners entry*\nAdd an owners entry for the path.",
    AttributionKind.STORY_ABSENT: (
        "*The story is not in the Storybook index*\nCheck whether it moved, was renamed, or was deleted."
    ),
}


@frozen
class Attribution:
    """The file behind one debt item, or the reason there is none.

    Never guessed from the identifier: a story name is not a path, and a wrong guess sends a team a
    reminder about somebody else's snapshot.
    """

    kind: AttributionKind
    # Repo-relative path of the story's file. Set only when the kind is PLACED.
    source_path: str = ""
    # Short phrase naming what stopped the lookup. Set only when the kind is UNAVAILABLE.
    detail: str = ""


@frozen
class DebtItem:
    """One thing somebody still has to decide about, and what is known about where it lives.

    Carries both renderings of itself, because Slack needs both: `facts` goes under the identity in
    a block, and `line` is the whole item on one line for the plain text a notification falls back
    to.
    """

    identifier: str
    run_type: str
    attribution: Attribution
    line: str
    facts: str


@frozen
class RepoDebt:
    """Everything one repo owes today, before it is split by owning team."""

    expiring_quarantines: list[DebtItem]
    variant_pileups: list[DebtItem]

    @property
    def items(self) -> list[DebtItem]:
        return [*self.expiring_quarantines, *self.variant_pileups]


@frozen
class TriageGroup:
    """The items that share one attribution outcome, and so one reason for having no owning team."""

    kind: AttributionKind
    items: list[DebtItem]


@frozen
class TeamDigest:
    """One team's share of a repo's debt, ready to post.

    Never empty. A team that owns nothing gets no message, so no team is told it owes nothing.
    """

    team_slug: str
    expiring_quarantines: list[DebtItem]
    variant_pileups: list[DebtItem]


@frozen
class MaintainersDigest:
    """The items nobody owns yet, and the team that holds them until somebody takes them."""

    team_slug: str
    groups: list[TriageGroup]


@frozen
class RepoDigests:
    """Everything one repo's run has to post: a digest per owning team, plus the unowned items."""

    teams: list[TeamDigest]
    maintainers: MaintainersDigest | None


@frozen
class SlackMessage:
    """One post: the blocks Slack renders, and the plain text it shows wherever they do not."""

    blocks: list[dict[str, Any]]
    text: str


@frozen
class MessagePart:
    """One block, and the plain line that stands in for it in the message's fallback text."""

    block: dict[str, Any]
    line: str


@frozen
class ReplyGroup:
    """One subject inside a message: a heading that says what to do, and the items it holds."""

    heading: MessagePart
    items: list[MessagePart]


@frozen
class Post:
    """One top-level Slack message and the replies that belong in its thread."""

    team_slug: str
    lead: SlackMessage
    replies: list[SlackMessage]
    item_count: int
    triage_count: int


@frozen
class Delivery:
    """Where one team's digest goes."""

    channel_id: str
    channel_name: str


def _snapshot_url(repo: Repo, run_type: str, identifier: str) -> str:
    return (
        f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/repos/{repo.id}"
        f"/{quote(run_type, safe='')}/snapshots/{quote(identifier, safe='')}"
    )


def _repo_snapshots_url(repo: Repo) -> str:
    """The repo's snapshot list. It names no snapshot, so its length does not follow the identifier."""
    return f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/repos/{repo.id}/snapshots"


def _repo_flakiness_url(repo: Repo) -> str:
    return f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/repos/{repo.id}/flakiness"


def _quarantined_story_url(repo: Repo, story: str) -> str:
    """The flakiness page narrowed to the quarantined snapshots of one story, in every theme.

    Falls back to the whole page when the search makes the URL too long for a Slack button.
    """
    url = f"{_repo_flakiness_url(repo)}#preset=quarantined&q={quote(story, safe='')}"
    return url if len(url) <= MAX_BUTTON_URL_CHARS else _repo_flakiness_url(repo)


def _snapshot_button(repo: Repo, item: DebtItem, text: str) -> SlackButton:
    """The item's button, pointing at the repo's list when the snapshot URL is too long for Slack.

    Same reason as `_linked_line` below: an encoded identifier can outgrow the cap on its own.
    """
    url = _snapshot_url(repo, item.run_type, item.identifier)
    return SlackButton(text=text, url=url if len(url) <= MAX_BUTTON_URL_CHARS else _repo_snapshots_url(repo))


def _linked_line(repo: Repo, body: str, run_type: str, identifier: str) -> str:
    """One item's line with its link, kept under the per-line cap.

    A non-ASCII identifier percent-encodes to nine characters each, so the snapshot URL alone can
    outgrow a Slack block however short the displayed text is cut. Point at the repo's snapshot
    list instead: the reader still gets a link, and one long item no longer costs the team the
    rest of its thread.
    """
    line = f"{body} · {_snapshot_url(repo, run_type, identifier)}"
    if len(line) <= _MAX_LINE_CHARS:
        return line
    listed = f" · listed under the repo's snapshots: {_repo_snapshots_url(repo)}"
    return f"{clip_text(body, _MAX_LINE_CHARS - len(listed))}{listed}"


def _monday_of(moment: datetime) -> date:
    return moment.date() - timedelta(days=moment.weekday())


def _month_day(day: date) -> str:
    """A date the way a person says it out loud, such as Sep 14."""
    return f"{day:%b} {day.day}"


def _expiry_word(expires_at: datetime | None, now: datetime) -> str:
    """When a quarantine runs out, said the way a reader plans a week.

    A weekday name only carries inside the coming week: seven days out it names the day the reader
    is reading on, so that one falls back to the date.
    """
    if expires_at is None:
        return "soon"
    days = (expires_at.date() - now.date()).days
    if days <= 0:
        return "today"
    if days < 7:
        return f"{expires_at:%A}"
    return _month_day(expires_at.date())


def _author_name(entry: QuarantinedIdentifier, authors: dict[int, str]) -> str:
    return escape_slack_mrkdwn(authors.get(entry.created_by_id or 0, "someone"))


def _quarantine_facts(entry: QuarantinedIdentifier, authors: dict[int, str], now: datetime) -> str:
    return (
        f"Expires *{_expiry_word(entry.expires_at, now)}* · opened by {_author_name(entry, authors)}\n"
        f'_"{escape_slack_mrkdwn(clip_text(entry.reason, _MAX_REASON_CHARS))}"_'
    )


def _pileup_facts(count: int) -> str:
    return f"*{count}* accepted variants of the current baseline"


def _quarantine_line(repo: Repo, entry: QuarantinedIdentifier, authors: dict[int, str], now: datetime) -> str:
    days = max((entry.expires_at - now).days, 0) if entry.expires_at is not None else 0
    body = (
        f"Quarantine expires in {days} days"
        f" · {escape_slack_mrkdwn(clip_text(entry.identifier, _MAX_IDENTIFIER_CHARS))}"
        f" ({escape_slack_mrkdwn(entry.run_type)})"
        f" · opened by {_author_name(entry, authors)}"
        f' for "{escape_slack_mrkdwn(clip_text(entry.reason, _MAX_REASON_CHARS))}"'
    )
    return _linked_line(repo, body, entry.run_type, entry.identifier)


def _pileup_line(repo: Repo, run_type: str, identifier: str, count: int) -> str:
    body = (
        f"{count} accepted variants of the current baseline"
        f" · {escape_slack_mrkdwn(clip_text(identifier, _MAX_IDENTIFIER_CHARS))} ({escape_slack_mrkdwn(run_type)})"
    )
    return _linked_line(repo, body, run_type, identifier)


def _display_names(user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return {
        user.id: user.first_name or user.email
        for user in User.objects.filter(id__in=user_ids).only("id", "first_name", "email")
    }


def _attribution_sources(
    repo: Repo, run_types: set[str], newest_run_by_type: Mapping[str, Run]
) -> dict[str, story_index.StoryIndex | str]:
    """What each run type in play can be attributed against: a story index, or why there is none.

    One map read per run type, not per item. A run type nothing owes today is never read, so a repo
    with no Storybook debt reads no map at all.
    """
    sources: dict[str, story_index.StoryIndex | str] = {}
    for run_type in run_types:
        if run_type != RunType.STORYBOOK:
            sources[run_type] = f"{run_type} runs are not supported yet"
            continue
        sources[run_type] = story_index.latest_story_index(repo, newest_run_by_type)
    return sources


def _attribution(sources: Mapping[str, story_index.StoryIndex | str], run_type: str, identifier: str) -> Attribution:
    """Where one snapshot's story lives, or why the index cannot say."""
    source = sources[run_type]
    if isinstance(source, str):
        return Attribution(kind=AttributionKind.UNAVAILABLE, detail=source)
    path = story_index.story_path(source, identifier)
    if path is None:
        return Attribution(kind=AttributionKind.STORY_ABSENT)
    return Attribution(kind=AttributionKind.PLACED, source_path=path)


def collect_debt(repo: Repo, now: datetime) -> RepoDebt:
    """Evaluate both conditions against current data, attribute each item, and render its line."""
    newest_run_by_type = run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo.id))
    expiring = quarantine.list_expiring_quarantines(repo.id, now=now, within_days=_DIGEST_EXPIRY_WINDOW_DAYS)
    quarantined_keys = quarantine.active_quarantine_keys(repo.id, now=now)
    piled_up = {
        key: count
        for key, count in toleration.count_active_variants_against_current_baseline(
            repo.id, now=now, newest_run_by_type=newest_run_by_type
        ).items()
        # Any live quarantine, expiring or not, already says somebody knows the snapshot is
        # unreliable, so asking them about the variants underneath it is a second reminder about
        # one problem.
        if count >= VARIANT_PILEUP_MIN and key not in quarantined_keys
    }

    run_types = {entry.run_type for entry in expiring} | {key.run_type for key in piled_up}
    sources = _attribution_sources(repo, run_types, newest_run_by_type)
    authors = _display_names({entry.created_by_id for entry in expiring if entry.created_by_id})

    return RepoDebt(
        expiring_quarantines=[
            DebtItem(
                identifier=entry.identifier,
                run_type=entry.run_type,
                attribution=_attribution(sources, entry.run_type, entry.identifier),
                line=_quarantine_line(repo, entry, authors, now),
                facts=_quarantine_facts(entry, authors, now),
            )
            for entry in expiring
        ],
        variant_pileups=[
            DebtItem(
                identifier=key.identifier,
                run_type=key.run_type,
                attribution=_attribution(sources, key.run_type, key.identifier),
                line=_pileup_line(repo, key.run_type, key.identifier, count),
                facts=_pileup_facts(count),
            )
            # Biggest pile first, then by identity so a tie reads the same way every morning.
            for key, count in sorted(
                piled_up.items(), key=lambda item: (-item[1], item[0].run_type, item[0].identifier)
            )
        ],
    )


def paths_to_resolve(debt: RepoDebt) -> list[str]:
    """Every path the run needs an owner for, including the product's own directory."""
    placed = {item.attribution.source_path for item in debt.items if item.attribution.kind == AttributionKind.PLACED}
    return [_PRODUCT_PATH, *sorted(placed)]


def _owning_team(item: DebtItem, ownership: PathOwnership) -> str:
    """The team that owns the item's story file, or `UNOWNED_TEAM` when there is nobody to name."""
    if item.attribution.kind != AttributionKind.PLACED:
        return UNOWNED_TEAM
    return ownership.team_by_path.get(item.attribution.source_path, UNOWNED_TEAM)


def split_by_team(debt: RepoDebt, ownership: PathOwnership) -> RepoDigests:
    """Group a repo's debt by the team that owns each item's story file.

    Everything else is not debt of the maintainers' own, so it goes to them as a message apart from
    their own digest, grouped by why it has no owner. When nobody owns the product directory either,
    the item is dropped with a log line rather than posted somewhere arbitrary.
    """
    fallback = ownership.team_by_path.get(_PRODUCT_PATH, UNOWNED_TEAM)
    expiring_by_team: dict[str, list[DebtItem]] = {}
    pileups_by_team: dict[str, list[DebtItem]] = {}
    triage_by_kind: dict[AttributionKind, list[DebtItem]] = {}
    for items, bucket in ((debt.expiring_quarantines, expiring_by_team), (debt.variant_pileups, pileups_by_team)):
        for item in items:
            team = _owning_team(item, ownership)
            if team != UNOWNED_TEAM:
                bucket.setdefault(team, []).append(item)
                continue
            if fallback == UNOWNED_TEAM:
                logger.info(
                    "visual_review.debt_digest_item_unowned",
                    identifier=item.identifier,
                    attribution=str(item.attribution.kind),
                    source_path=item.attribution.source_path,
                )
                continue
            triage_by_kind.setdefault(item.attribution.kind, []).append(item)

    # Declaration order, so the three groups always read in the same order.
    triage = [TriageGroup(kind=kind, items=triage_by_kind[kind]) for kind in AttributionKind if kind in triage_by_kind]
    return RepoDigests(
        teams=[
            TeamDigest(
                team_slug=team,
                expiring_quarantines=expiring_by_team.get(team, []),
                variant_pileups=pileups_by_team.get(team, []),
            )
            for team in sorted(expiring_by_team.keys() | pileups_by_team.keys())
        ],
        maintainers=MaintainersDigest(team_slug=fallback, groups=triage) if triage else None,
    )


def _message(parts: Sequence[MessagePart]) -> SlackMessage:
    """One post from its parts. A part with no line of its own, such as a divider, adds none."""
    text = "\n".join(part.line for part in parts if part.line)
    # Slack cuts a fallback over the cap without saying so, and the blocks carry every item anyway.
    return SlackMessage(blocks=[part.block for part in parts], text=clip_text(text, MAX_TEXT_CHARS))


def _split_into_messages(
    groups: Sequence[ReplyGroup], footer: Sequence[MessagePart], preamble: Sequence[MessagePart] = ()
) -> list[SlackMessage]:
    """One message per group, split again when a group holds more items than Slack takes in a post.

    A group with no items produces no message at all. The heading repeats on a continuation, because
    a message that opens with an item says nothing about what the reader is looking at.
    """
    parts_by_message: list[list[MessagePart]] = []
    for group in groups:
        for start in range(0, len(group.items), _ITEMS_PER_MESSAGE):
            parts_by_message.append([group.heading, *group.items[start : start + _ITEMS_PER_MESSAGE]])
    if not parts_by_message:
        return []
    parts_by_message[0] = [*preamble, *parts_by_message[0]]
    parts_by_message[-1].extend(footer)
    return [_message(parts) for parts in parts_by_message]


def _heading_part(text: str) -> MessagePart:
    return MessagePart(block=section_block(text), line=text)


def _header_part(text: str) -> MessagePart:
    return MessagePart(block=header_block(text), line=text)


def _context_part(text: str) -> MessagePart:
    return MessagePart(block=context_block(text), line=text)


def _closing_parts(text: str) -> list[MessagePart]:
    """A rule and one line of small print, which is how a message signs off."""
    return [MessagePart(block=divider_block(), line=""), _context_part(text)]


@frozen
class ListedEntry:
    """What one section of a reply lists: one snapshot, or the theme variants of one story that share every fact."""

    items: list[DebtItem]
    # The identifier the section shows. Merged variants show it without the theme.
    identifier: str
    # Empty for a single snapshot.
    themes: list[str]


def _single_entry(item: DebtItem) -> ListedEntry:
    return ListedEntry(items=[item], identifier=item.identifier, themes=[])


def _merge_theme_variants(items: Sequence[DebtItem]) -> list[ListedEntry]:
    """The items as entries, with the theme variants of one story merged into its first entry.

    A story snapshots once per theme, so one unreliable story usually lists twice. Variants merge
    only when the reader sees the same facts for each, so the merge hides nothing.
    """
    groups: list[list[DebtItem]] = []
    open_groups: dict[tuple[str, str, str, Attribution], list[DebtItem]] = {}
    for item in items:
        split = story_index.split_theme(item.identifier)
        if not split.theme:
            groups.append([item])
            continue
        key = (item.run_type, split.rest, item.facts, item.attribution)
        group = open_groups.get(key)
        if group is None or any(other.identifier == item.identifier for other in group):
            group = []
            open_groups[key] = group
            groups.append(group)
        group.append(item)

    entries: list[ListedEntry] = []
    for group in groups:
        if len(group) == 1:
            entries.append(_single_entry(group[0]))
            continue
        splits = [story_index.split_theme(item.identifier) for item in group]
        entries.append(ListedEntry(items=group, identifier=splits[0].rest, themes=[split.theme for split in splits]))
    return entries


def _item_text(entry: ListedEntry, extra: str = "") -> str:
    """One entry's section: what it is, then its facts, then whatever its group adds under them."""
    first = entry.items[0]
    themes = f" · {human_list(entry.themes)}" if entry.themes else ""
    title = (
        f"*{escape_slack_mrkdwn(clip_text(entry.identifier, _MAX_IDENTIFIER_CHARS))}* "
        f"{escape_slack_mrkdwn(first.run_type)}{themes}"
    )
    return clip_text("\n".join(part for part in (title, first.facts, extra) if part), MAX_SECTION_CHARS)


def _item_part(repo: Repo, item: DebtItem, button_text: str, line: str | None = None) -> MessagePart:
    return MessagePart(
        block=section_block(_item_text(_single_entry(item)), _snapshot_button(repo, item, button_text)),
        line=item.line if line is None else line,
    )


def _quarantine_part(repo: Repo, entry: ListedEntry) -> MessagePart:
    """One expiring quarantine, or the theme variants of one story that expire together.

    A merged entry links to the flakiness page, because the snapshot page shows one theme and each
    variant needs the same extension.
    """
    if not entry.themes:
        return _item_part(repo, entry.items[0], "Extend or fix")
    # The page searches identifiers by substring, and a webkit identifier puts the theme before the
    # browser suffix, so only the bare story id matches every variant.
    story_id = story_index.split_theme(entry.items[0].identifier).story_id
    button = SlackButton(text="Extend or fix", url=_quarantined_story_url(repo, story_id))
    return MessagePart(
        block=section_block(_item_text(entry), button), line="\n".join(item.line for item in entry.items)
    )


def _footer_parts(now: datetime) -> list[MessagePart]:
    """What closes the last reply: when the next one comes."""
    return _closing_parts(f"Next digest Monday, {_month_day(_monday_of(now) + timedelta(days=7))}.")


def _count_phrases(digest: TeamDigest, emphasis: str = "") -> list[str]:
    """How much of each condition the team carries. A condition with no items is left out, because a
    zero count reads as one more thing to look at."""
    phrases: list[str] = []
    expiring = len(digest.expiring_quarantines)
    if expiring:
        phrases.append(
            f"{emphasis}{pluralize(expiring, 'quarantine')}{emphasis} expire{'s' if expiring == 1 else ''} soon"
        )
    pileups = len(digest.variant_pileups)
    if pileups:
        phrases.append(f"{emphasis}{pluralize(pileups, 'snapshot')}{emphasis} with piled-up variants")
    return phrases


def lead_text(repo: Repo, digest: TeamDigest) -> str:
    """The lead as one sentence, for the notification Slack shows before the blocks render."""
    return clip_text(
        f"Visual review debt for {digest.team_slug} in {repo.repo_full_name}: {', '.join(_count_phrases(digest))}.",
        MAX_SECTION_CHARS,
    )


def lead_message(repo: Repo, digest: TeamDigest, now: datetime) -> SlackMessage:
    """What lands in the channel: the team, the week, the counts, and the pages behind them."""
    return SlackMessage(
        blocks=[
            header_block(f"Visual review debt for {digest.team_slug}"),
            context_block(f"{repo.repo_full_name} · week of {_month_day(_monday_of(now))} · weekly digest"),
            fields_block(_count_phrases(digest, emphasis="*")),
            section_block(f"{_LEAD_BODY} {_LEAD_LAPSE_NOTE}" if digest.expiring_quarantines else _LEAD_BODY),
            actions_block(
                [
                    SlackButton(
                        text="Open flakiness overview",
                        url=f"{_repo_flakiness_url(repo)}#teams={quote(digest.team_slug, safe='')}",
                        primary=True,
                    ),
                    SlackButton(text="Open snapshots", url=_repo_snapshots_url(repo)),
                ]
            ),
        ],
        text=lead_text(repo, digest),
    )


def thread_messages(repo: Repo, digest: TeamDigest, now: datetime) -> list[SlackMessage]:
    """One reply per condition that has items, each item carrying the action that resolves it."""
    groups = [
        ReplyGroup(
            heading=_heading_part(_QUARANTINE_HEADING),
            items=[_quarantine_part(repo, entry) for entry in _merge_theme_variants(digest.expiring_quarantines)],
        ),
        ReplyGroup(
            heading=_heading_part(_PILEUP_HEADING),
            items=[_item_part(repo, item, "Reset baseline") for item in digest.variant_pileups],
        ),
    ]
    return _split_into_messages(groups, _footer_parts(now))


def _triage_line(item: DebtItem) -> str:
    """One triage item's line, carrying what its group's heading asks the reader to act on."""
    if item.attribution.kind == AttributionKind.PLACED:
        return f"{item.line} · {escape_slack_mrkdwn(item.attribution.source_path)}"
    if item.attribution.kind == AttributionKind.UNAVAILABLE:
        return f"{item.line} · {escape_slack_mrkdwn(item.attribution.detail)}"
    return item.line


def _file_button(repo: Repo, item: DebtItem) -> SlackButton | None:
    """The story's file on the default branch, which is where an owners entry is written against.

    None when the URL is longer than Slack accepts. A long or non-ASCII path can outgrow the cap on
    its own, and Slack refuses the whole message over one oversized button. The path is in the
    section text as well, so leaving the button out costs the reader the link and nothing else.
    """
    path = quote(item.attribution.source_path)
    url = f"https://github.com/{repo.repo_full_name}/blob/HEAD/{path}"
    return SlackButton(text="Open file", url=url) if len(url) <= MAX_BUTTON_URL_CHARS else None


def _placed_part(repo: Repo, entry: ListedEntry) -> MessagePart:
    """One unowned story file. Theme variants share the file, so one button covers all of them."""
    first = entry.items[0]
    # The path stays in the text as well as behind the button, because it is what somebody types
    # into owners.yaml.
    text = _item_text(entry, f"`{escape_slack_mrkdwn(first.attribution.source_path)}`")
    return MessagePart(
        block=section_block(text, _file_button(repo, first)), line="\n".join(_triage_line(item) for item in entry.items)
    )


def _triage_group(repo: Repo, group: TriageGroup) -> ReplyGroup:
    """One reason for having no owner, and the items behind it."""
    if group.kind == AttributionKind.PLACED:
        items = [_placed_part(repo, entry) for entry in _merge_theme_variants(group.items)]
    else:
        items = [_item_part(repo, item, "Open snapshot", line=_triage_line(item)) for item in group.items]
    return ReplyGroup(heading=_heading_part(_TRIAGE_HEADINGS[group.kind]), items=items)


def _unavailable_parts(items: Sequence[DebtItem]) -> list[MessagePart]:
    """What closes the maintainers' message when a run could not read the index for some items.

    They are counted rather than listed, because they ask the reader for nothing: the fix is another
    run against another baseline, not a decision anybody makes this week. The reasons stay in the
    log, where whoever maintains the digest looks for them.
    """
    if not items:
        return []
    logger.info(
        "visual_review.debt_digest_ownership_unreadable",
        item_count=len(items),
        details=sorted({item.attribution.detail for item in items if item.attribution.detail}),
    )
    count = len(items)
    return _closing_parts(
        f"{count} item{'' if count == 1 else 's'} with no readable Storybook index this week "
        f"{'is' if count == 1 else 'are'} not listed. Ownership is read again next Monday."
    )


def maintainers_messages(repo: Repo, digest: MaintainersDigest) -> list[SlackMessage]:
    """The unowned items as their own post, or nothing when none of them asks anybody to act."""
    groups = [_triage_group(repo, group) for group in digest.groups if group.kind in _TRIAGE_HEADINGS]
    if not groups:
        return []
    listed = sum(len(group.items) for group in groups)
    unavailable = [item for group in digest.groups if group.kind == AttributionKind.UNAVAILABLE for item in group.items]
    preamble = [
        _header_part(f"Unowned visual review debt in {repo.repo_full_name}"),
        _context_part(
            f"{listed} item{'' if listed == 1 else 's'} nobody owns yet · sent to the visual review maintainers"
        ),
    ]
    return _split_into_messages(groups, _unavailable_parts(unavailable), preamble)


def resolve_channel(
    team_slug: str, registry: Mapping[str, TeamEntry], channels_by_name: Mapping[str, SlackChannel]
) -> Delivery | None:
    """The team's own notifications channel, or None when it opted out or the name does not resolve."""
    answer = team_channel(team_slug, registry, _CHANNEL_PURPOSE, _PRODUCER)
    if answer.channel is None:
        logger.info("visual_review.debt_digest_team_opted_out", team_slug=team_slug)
        return None
    name = answer.channel.removeprefix("#")
    match = find_channel(channels_by_name, name, allow_shared=False)
    if match.channel is None:
        logger.info(
            "visual_review.debt_digest_channel_unusable",
            team_slug=team_slug,
            channel_name=name,
            reason=match.reason,
        )
        return None
    return Delivery(channel_id=match.channel.channel_id, channel_name=name)


def plan_posts(repo: Repo, digests: RepoDigests, now: datetime) -> list[Post]:
    """Every message this run sends, in the order it sends them.

    A team is here only when it owns something, so no team is ever told it owns nothing. The
    maintainers appear once for their own debt and again for what nobody owns, because the two ask
    different things of them.
    """
    posts = [
        Post(
            team_slug=digest.team_slug,
            lead=lead_message(repo, digest, now),
            replies=thread_messages(repo, digest, now),
            item_count=len(digest.expiring_quarantines) + len(digest.variant_pileups),
            triage_count=0,
        )
        for digest in digests.teams
    ]
    maintainers = digests.maintainers
    if maintainers is not None:
        messages = maintainers_messages(repo, maintainers)
        if messages:
            posts.append(
                Post(
                    team_slug=maintainers.team_slug,
                    lead=messages[0],
                    replies=messages[1:],
                    item_count=0,
                    triage_count=sum(len(group.items) for group in maintainers.groups),
                )
            )
    return posts


def send_debt_digest(repo: Repo, mode: str) -> list[str]:
    """Evaluate, attribute, and post one repo's digest. One team's failure does not stop the rest.

    Returns each post's plain text, so an operator running this by hand can read what the run would
    send without reaching into the logs.
    """
    # Anything that is not preview posts, so an undefined mode must stop here rather than go live.
    if mode not in MODES:
        logger.warning("visual_review.debt_digest_mode_unknown", mode=mode)
        return []

    now = timezone.now()
    debt = collect_debt(repo, now)
    if not debt.items:
        logger.info("visual_review.debt_digest_nothing_owed", repo_id=str(repo.id), team_id=repo.team_id)
        return []

    ownership = resolve_path_owners(repo.repo_full_name, paths_to_resolve(debt))
    if not ownership.resolved:
        # A blind answer names no team and carries no registry, so every item would read as
        # unowned and be dropped. Say so instead, and send the same items next week.
        logger.warning("visual_review.debt_digest_ownership_unavailable", repo_id=str(repo.id), team_id=repo.team_id)
        return []
    posts = plan_posts(repo, split_by_team(debt, ownership), now)

    if mode == MODE_PREVIEW:
        return [_preview_one(repo, post, ownership.registry) for post in posts]

    integration = Integration.objects.filter(team_id=repo.team_id, kind="slack").first()
    if integration is None:
        logger.info("visual_review.debt_digest_no_slack_integration", team_id=repo.team_id)
        return []
    channels_by_name = fetch_channel_map(integration)

    rendered: list[str] = []
    for post in posts:
        try:
            rendered.append(_send_one(repo, post, ownership.registry, channels_by_name, integration))
        except Exception as e:
            # One team's Slack failure must not cost the rest of the repo its reminder, and there is
            # nothing to retry against: next Monday's run sends the same items again.
            logger.warning(
                "visual_review.debt_digest_team_failed",
                repo_id=str(repo.id),
                team_slug=post.team_slug,
                error=str(e),
            )
    return rendered


def _post_text(post: Post) -> str:
    return "\n".join([post.lead.text, *(reply.text for reply in post.replies)])


def _preview_one(repo: Repo, post: Post, registry: Mapping[str, TeamEntry]) -> str:
    """Render one post and log it, without reading Slack at all."""
    rendered = _post_text(post)
    # Preview holds no channel map, because fetching one needs the integration it deliberately does
    # not touch. So the routing here only ever reports the team's own opt-out.
    resolved = resolve_channel(post.team_slug, registry, {})
    logger.info(
        "visual_review.debt_digest_preview",
        repo_id=str(repo.id),
        team_slug=post.team_slug,
        channel_name=resolved.channel_name if resolved is not None else None,
        item_count=post.item_count,
        triage_count=post.triage_count,
        rendered=rendered,
    )
    return rendered


def _send_one(
    repo: Repo,
    post: Post,
    registry: Mapping[str, TeamEntry],
    channels_by_name: Mapping[str, SlackChannel],
    integration: Integration,
) -> str:
    delivery = resolve_channel(post.team_slug, registry, channels_by_name)
    if delivery is None:
        return ""

    slack = SlackIntegration(integration)
    try:
        thread_ts = post_with_join(
            slack, delivery.channel_id, post.lead.blocks, post.lead.text, channel_name=delivery.channel_name
        )
    except SlackPostRefused as e:
        logger.warning("visual_review.debt_digest_post_refused", team_slug=post.team_slug, error=str(e))
        return ""
    # Without a parent to hang them on, the item blocks land in the channel as separate top-level
    # posts, which is the noise the thread exists to remove.
    if thread_ts is not None:
        for reply in post.replies:
            post_message(slack, delivery.channel_id, reply.blocks, reply.text, thread_ts=thread_ts)
    return _post_text(post)


def repos_in_scope() -> list[Repo]:
    """Every repo that opted in, oldest first.

    The switch is the only way to stop the digest without a deploy, so the fan-out reads it rather
    than the per-repo task: a repo that is off costs no child task at all, and it reads no Storybook
    artifact on the runs that only warm the cache. The fan-out only routes, so the rows stay
    unhydrated.
    """
    # nosemgrep: idor-lookup-without-team — cross-team beat sweep, no user input
    return list(Repo.objects.unscoped().filter(debt_digest_enabled=True).only("id", "team_id").order_by("created_at"))
