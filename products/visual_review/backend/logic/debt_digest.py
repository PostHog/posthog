"""The daily reminder about visual review debt a team is still carrying.

Stateless by design. Every morning the two conditions below are evaluated from current data,
attributed to the team that owns the file the snapshot's story lives in today, and posted. Nothing
is stored about what was sent, so an item repeats every day until the condition stops holding and
disappears the moment it does. A team whose post fails is logged and the run moves on; tomorrow
recomputes everything from scratch.

The two conditions:

  Quarantine expiring. An active quarantine that runs out inside `FLAKINESS_EXPIRY_SOON_DAYS`.
  Somebody has to extend it, lift it, or decide to let it lapse.

  Variant pile-up. `VARIANT_PILEUP_MIN` or more accepted variants standing against the baseline's
  current hash, with no quarantine already covering the identity. The baseline has stopped
  describing one rendering.

A baseline change clears the second condition, and that is not the same as the story recovering: it
invalidates the tolerations recorded against the old baseline, because they can never match again.
Nothing here claims a snapshot got better.

Attribution runs through the Storybook build behind the current baseline. Its story index names the
file each story lives in, and the repository's own ownership files name the team that owns that file.
Three things stop that: no owners entry covers the file, the index has no such story, or there is no
index to read. All three go to the visual review maintainers as triage, kept apart from the items
those maintainers own, because holding an item until a team takes it is not owning it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import field
from datetime import datetime
from enum import StrEnum
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
    MAX_SECTION_CHARS,
    SlackChannel,
    SlackPostRefused,
    clip_text,
    fetch_channel_map,
    find_channel,
    post_message,
    post_with_join,
    section_block,
)

from products.engineering_analytics.backend.facade.api import resolve_path_owners
from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM, PathOwnership

from ..facade.contracts import VARIANT_PILEUP_MIN
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

# Said of a run type whose items have no default-branch run to attribute against.
_NO_BASELINE_RUN_DETAIL = "there is no default branch run to read"

_MAX_LINE_CHARS = MAX_SECTION_CHARS // 2
# The full identifier still goes into the URL, so a cut display costs the reader nothing.
_MAX_IDENTIFIER_CHARS = 160
_MAX_REASON_CHARS = 200

MODE_PREVIEW = "preview"
MODE_LIVE = "live"
MODES = (MODE_PREVIEW, MODE_LIVE)

_FOOTER = (
    "This repeats daily while the items stay unresolved. "
    "To opt out, set notifications: {visual_review: false} under your team in owners.yaml."
)


class AttributionKind(StrEnum):
    """What the story index can say about the file behind one snapshot."""

    PLACED = "placed"  # the story maps to a file in the repository
    STORY_ABSENT = "story_absent"  # the index was read, and it holds no such story
    UNAVAILABLE = "unavailable"  # there is no index to ask for this run type today


# Each outcome asks the reader for a different fix. A placed path in triage is one no owners entry covers.
_TRIAGE_HEADERS: dict[AttributionKind, str] = {
    AttributionKind.PLACED: "*Nobody owns the file yet.* Add an owners entry for the path at the end of each line.",
    AttributionKind.STORY_ABSENT: (
        "*The story is not in the Storybook index.* Check whether it moved, was renamed, or was deleted."
    ),
    AttributionKind.UNAVAILABLE: (
        "*Ownership could not be worked out today.* Nothing to do, the digest tries again tomorrow."
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
    """One thing somebody still has to decide about, and what is known about where it lives."""

    identifier: str
    run_type: str
    attribution: Attribution
    line: str


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
    """One team's share of a repo's debt, ready to post."""

    team_slug: str
    expiring_quarantines: list[DebtItem]
    variant_pileups: list[DebtItem]
    # Items nobody owns yet. Only the maintainers' digest carries them, and they hold them until a
    # team takes them.
    triage: list[TriageGroup] = field(default_factory=list)


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


def _quarantine_line(repo: Repo, entry: QuarantinedIdentifier, authors: dict[int, str], now: datetime) -> str:
    days = max((entry.expires_at - now).days, 0) if entry.expires_at is not None else 0
    who = authors.get(entry.created_by_id or 0, "someone")
    body = (
        f"Quarantine expires in {days} days"
        f" · {escape_slack_mrkdwn(clip_text(entry.identifier, _MAX_IDENTIFIER_CHARS))}"
        f" ({escape_slack_mrkdwn(entry.run_type)})"
        f' · opened by {escape_slack_mrkdwn(who)} for "{escape_slack_mrkdwn(clip_text(entry.reason, _MAX_REASON_CHARS))}"'
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


def _workflow_run_id(run: Run) -> str | None:
    """The GitHub workflow run that produced one run, or None when the run records none.

    Read on a query of its own because the shared default-branch universe defers `metadata`. Every
    other reader of that universe needs the run ids alone, so it stays lean for the pages that use
    it.
    """
    metadata = Run.objects.filter(id=run.id).values_list("metadata", flat=True).first()
    github_run_id = (metadata or {}).get("github_run_id")
    return github_run_id if isinstance(github_run_id, str) and github_run_id else None


def _attribution_sources(
    repo: Repo, run_types: set[str], newest_run_by_type: Mapping[str, Run]
) -> dict[str, story_index.StoryIndex | str]:
    """What each run type in play can be attributed against: a story index, or why there is none.

    One artifact read per run type, not per item. A run type nothing owes today is never read, so a
    repo with no Storybook debt costs no download at all.
    """
    sources: dict[str, story_index.StoryIndex | str] = {}
    for run_type in run_types:
        if run_type != RunType.STORYBOOK:
            sources[run_type] = f"{run_type} runs are not supported yet"
            continue
        run = newest_run_by_type.get(run_type)
        if run is None:
            sources[run_type] = _NO_BASELINE_RUN_DETAIL
            continue
        github_run_id = _workflow_run_id(run)
        if github_run_id is None:
            sources[run_type] = "the run behind the baseline records no workflow run"
            continue
        index = story_index.fetch_story_index(repo, github_run_id)
        sources[run_type] = (
            index if index is not None else f"the Storybook build artifact for run {github_run_id} was not read"
        )
    return sources


def _attribution(sources: Mapping[str, story_index.StoryIndex | str], run_type: str, identifier: str) -> Attribution:
    """Where one snapshot's story lives, or why the index cannot say."""
    source = sources.get(run_type)
    if source is None:
        return Attribution(kind=AttributionKind.UNAVAILABLE, detail=_NO_BASELINE_RUN_DETAIL)
    if isinstance(source, str):
        return Attribution(kind=AttributionKind.UNAVAILABLE, detail=source)
    path = story_index.story_path(source, identifier)
    if path is None:
        return Attribution(kind=AttributionKind.STORY_ABSENT)
    return Attribution(kind=AttributionKind.PLACED, source_path=path)


def collect_debt(repo: Repo, now: datetime) -> RepoDebt:
    """Evaluate both conditions against current data, attribute each item, and render its line."""
    newest_run_by_type = run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo.id))
    expiring = quarantine.list_expiring_quarantines(repo.id, now=now)
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
            )
            for entry in expiring
        ],
        variant_pileups=[
            DebtItem(
                identifier=key.identifier,
                run_type=key.run_type,
                attribution=_attribution(sources, key.run_type, key.identifier),
                line=_pileup_line(repo, key.run_type, key.identifier, count),
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


def split_by_team(debt: RepoDebt, ownership: PathOwnership) -> list[TeamDigest]:
    """Group a repo's debt by the team that owns each item's story file.

    Everything else is triage rather than debt of the maintainers' own: it goes into the digest of
    the team that owns the product directory, grouped by why it has no owner. When that team is
    unowned too, the item is dropped with a log line rather than posted somewhere arbitrary.
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
    teams = expiring_by_team.keys() | pileups_by_team.keys()
    if triage:
        teams = teams | {fallback}
    return [
        TeamDigest(
            team_slug=team,
            expiring_quarantines=expiring_by_team.get(team, []),
            variant_pileups=pileups_by_team.get(team, []),
            triage=triage if team == fallback else [],
        )
        for team in sorted(teams)
    ]


def _unavailable_details(digest: TeamDigest) -> list[str]:
    """Every distinct reason ownership could not be worked out for this digest's triage items."""
    return sorted(
        {item.attribution.detail for group in digest.triage for item in group.items if item.attribution.detail}
    )


def lead_text(digest: TeamDigest, repo: Repo) -> str:
    expiring = len(digest.expiring_quarantines)
    pileups = len(digest.variant_pileups)
    # A digest that carries triage only still names the team and the repo, so the maintainers can
    # see whose channel it landed in without opening the thread.
    owed = (
        f"{expiring} quarantine{'' if expiring == 1 else 's'} expire{'s' if expiring == 1 else ''} soon, "
        f"{pileups} snapshot{'' if pileups == 1 else 's'} with piled-up variants."
        if expiring or pileups
        else "nothing this team owns today."
    )
    sentences = [f"Visual review debt for {digest.team_slug} in {repo.repo_full_name}: {owed}"]
    triage_count = sum(len(group.items) for group in digest.triage)
    if triage_count:
        sentences.append(
            f"Plus {triage_count} in triage that nobody owns yet: visual review maintainers hold them "
            "until a team takes them."
        )
    details = _unavailable_details(digest)
    if details:
        sentences.append(
            "Ownership could not be worked out for some of them today, because "
            f"{escape_slack_mrkdwn('; '.join(details))}. The digest tries again tomorrow."
        )
    # The lead is one Slack section like every thread line, so it takes the same cap.
    return clip_text(" ".join(sentences), MAX_SECTION_CHARS)


def _triage_line(item: DebtItem) -> str:
    """One triage item's line, carrying what its group's header asks the reader to act on."""
    if item.attribution.kind == AttributionKind.PLACED:
        return f"{item.line} · {escape_slack_mrkdwn(item.attribution.source_path)}"
    if item.attribution.kind == AttributionKind.UNAVAILABLE:
        return f"{item.line} · {escape_slack_mrkdwn(item.attribution.detail)}"
    return item.line


def thread_texts(digest: TeamDigest) -> list[str]:
    """The item lines, grouped by condition and then by triage reason, split to fit Slack's section cap."""
    lines = [
        *(item.line for item in digest.expiring_quarantines),
        *(item.line for item in digest.variant_pileups),
    ]
    for group in digest.triage:
        lines.append(_TRIAGE_HEADERS[group.kind])
        lines.extend(_triage_line(item) for item in group.items)
    lines.append(_FOOTER)
    # A cut line costs one reader one path; a line Slack refuses costs the team the rest of the thread.
    lines = [clip_text(line, MAX_SECTION_CHARS) for line in lines]
    messages: list[str] = []
    current: list[str] = []
    for line in lines:
        if current and len("\n".join([*current, line])) > MAX_SECTION_CHARS:
            messages.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        messages.append("\n".join(current))
    return messages


def resolve_channel(
    digest: TeamDigest, registry: Mapping[str, TeamEntry], channels_by_name: Mapping[str, SlackChannel]
) -> Delivery | None:
    """The team's own notifications channel, or None when it opted out or the name does not resolve."""
    answer = team_channel(digest.team_slug, registry, _CHANNEL_PURPOSE, _PRODUCER)
    if answer.channel is None:
        logger.info("visual_review.debt_digest_team_opted_out", team_slug=digest.team_slug)
        return None
    name = answer.channel.removeprefix("#")
    match = find_channel(channels_by_name, name, allow_shared=False)
    if match.channel is None:
        logger.info(
            "visual_review.debt_digest_channel_unusable",
            team_slug=digest.team_slug,
            channel_name=name,
            reason=match.reason,
        )
        return None
    return Delivery(channel_id=match.channel.channel_id, channel_name=name)


def send_debt_digest(repo: Repo, mode: str) -> list[str]:
    """Evaluate, attribute, and post one repo's digest. One team's failure does not stop the rest.

    Returns each team's rendered message, so an operator running this by hand can read what the
    run would send without reaching into the logs.
    """
    # Anything that is not preview posts, so an undefined mode must stop here rather than go live.
    if mode not in MODES:
        logger.warning("visual_review.debt_digest_mode_unknown", mode=mode)
        return []

    debt = collect_debt(repo, timezone.now())
    if not debt.items:
        logger.info("visual_review.debt_digest_nothing_owed", repo_id=str(repo.id), team_id=repo.team_id)
        return []

    ownership = resolve_path_owners(repo.repo_full_name, paths_to_resolve(debt))
    if not ownership.resolved:
        # A blind answer names no team and carries no registry, so every item would read as
        # unowned and be dropped. Say so instead, and send the same items tomorrow.
        logger.warning("visual_review.debt_digest_ownership_unavailable", repo_id=str(repo.id), team_id=repo.team_id)
        return []
    digests = split_by_team(debt, ownership)

    if mode == MODE_PREVIEW:
        return [_preview_one(repo, digest, ownership.registry) for digest in digests]

    integration = Integration.objects.filter(team_id=repo.team_id, kind="slack").first()
    if integration is None:
        logger.info("visual_review.debt_digest_no_slack_integration", team_id=repo.team_id)
        return []
    channels_by_name = fetch_channel_map(integration)

    rendered: list[str] = []
    for digest in digests:
        try:
            rendered.append(_send_one(repo, digest, ownership.registry, channels_by_name, integration))
        except Exception as e:
            # One team's Slack failure must not cost the rest of the repo its reminder, and there is
            # nothing to retry against: tomorrow's run sends the same items again.
            logger.warning(
                "visual_review.debt_digest_team_failed",
                repo_id=str(repo.id),
                team_slug=digest.team_slug,
                error=str(e),
            )
    return rendered


def _preview_one(repo: Repo, digest: TeamDigest, registry: Mapping[str, TeamEntry]) -> str:
    """Render one team's digest and log it, without reading Slack at all."""
    rendered = "\n".join([lead_text(digest, repo), *thread_texts(digest)])
    # Preview holds no channel map, because fetching one needs the integration it deliberately does
    # not touch. So the routing here only ever reports the team's own opt-out.
    resolved = resolve_channel(digest, registry, {})
    logger.info(
        "visual_review.debt_digest_preview",
        repo_id=str(repo.id),
        team_slug=digest.team_slug,
        channel_name=resolved.channel_name if resolved is not None else None,
        item_count=len(digest.expiring_quarantines) + len(digest.variant_pileups),
        triage_count=sum(len(group.items) for group in digest.triage),
        rendered=rendered,
    )
    return rendered


def _send_one(
    repo: Repo,
    digest: TeamDigest,
    registry: Mapping[str, TeamEntry],
    channels_by_name: Mapping[str, SlackChannel],
    integration: Integration,
) -> str:
    lead = lead_text(digest, repo)
    thread = thread_texts(digest)
    delivery = resolve_channel(digest, registry, channels_by_name)
    if delivery is None:
        return ""

    slack = SlackIntegration(integration)
    try:
        thread_ts = post_with_join(
            slack, delivery.channel_id, section_block(lead), lead, channel_name=delivery.channel_name
        )
    except SlackPostRefused as e:
        logger.warning("visual_review.debt_digest_post_refused", team_slug=digest.team_slug, error=str(e))
        return ""
    # Without a parent to hang them on, the item lines land in the channel as separate top-level
    # posts, which is the noise the thread exists to remove.
    if thread_ts is not None:
        for text in thread:
            post_message(slack, delivery.channel_id, section_block(text), text, thread_ts=thread_ts)
    return "\n".join([lead, *thread])


def repos_in_scope() -> list[Repo]:
    """Every repo, oldest first.

    No allowlist: the per-repo task stops as soon as a repo owes nothing, so a repo that never
    carries debt costs one cheap read a day. The fan-out only routes, so the rows stay unhydrated.
    """
    # nosemgrep: idor-lookup-without-team — cross-team beat sweep, no user input
    return list(Repo.objects.unscoped().only("id", "team_id").order_by("created_at"))
