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

from collections.abc import Mapping, Sequence
from dataclasses import field
from datetime import datetime
from enum import StrEnum
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

import structlog
from posthog_owners.resolver import Purpose, team_channel
from posthog_owners.schema import Producer, TeamEntry

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.team_notifications.slack import (
    SlackChannel,
    SlackPostRefused,
    fetch_channel_map,
    find_channel,
    post_message,
    post_with_join,
)

from products.engineering_analytics.backend.facade.api import resolve_path_owners
from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM, PathOwnership

from ..facade.contracts import VARIANT_PILEUP_MIN
from ..facade.enums import RunType
from ..models import QuarantinedIdentifier, Repo
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

# Slack rejects a section block over 3000 characters. The margin covers the mrkdwn escaping, which
# can turn one character into five.
_MAX_SECTION_CHARS = 2900

MODE_OFF = "off"
MODE_PREVIEW = "preview"
MODE_SHADOW = "shadow"
MODE_LIVE = "live"
MODES = (MODE_OFF, MODE_PREVIEW, MODE_SHADOW, MODE_LIVE)

_FOOTER = (
    "This repeats daily while the items stay unresolved. "
    "To opt out, set notifications: {visual_review: false} under your team in owners.yaml."
)


class AttributionKind(StrEnum):
    """What the story index can say about the file behind one snapshot."""

    PLACED = "placed"  # the story maps to a file in the repository
    STORY_ABSENT = "story_absent"  # the index was read, and it holds no such story
    UNAVAILABLE = "unavailable"  # there is no index to ask for this run type today


class TriageReason(StrEnum):
    """Why an item has no owning team, and therefore sits with the visual review maintainers.

    The three are kept apart everywhere, because each asks for a different fix: an owners entry, a
    look at what happened to the story, or nothing at all.
    """

    UNOWNED_FILE = "unowned_file"
    STORY_ABSENT = "story_absent"
    UNAVAILABLE = "unavailable"


_TRIAGE_HEADERS: dict[TriageReason, str] = {
    TriageReason.UNOWNED_FILE: (
        "*Nobody owns the file yet.* Add an owners entry for the path at the end of each line."
    ),
    TriageReason.STORY_ABSENT: (
        "*The story is not in the Storybook index.* Check whether it moved, was renamed, or was deleted."
    ),
    TriageReason.UNAVAILABLE: (
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
    """The items that share one reason for having no owning team."""

    reason: TriageReason
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
    """Where one team's digest goes, and what the lead says about how it got there."""

    channel_id: str
    channel_name: str
    lead_prefix: str


def _escape_mrkdwn(text: str) -> str:
    """Neutralize Slack mrkdwn control characters in text a contributor wrote.

    A quarantine reason and a snapshot identifier are both user input. Escaping `&`, `<` and `>`
    stops one from smuggling a `<!channel>` mention or breaking out of a link; Slack renders the
    escaped entities back as the literal characters.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _snapshot_url(repo: Repo, run_type: str, identifier: str) -> str:
    return (
        f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/repos/{repo.id}"
        f"/{quote(run_type, safe='')}/snapshots/{quote(identifier, safe='')}"
    )


def _quarantine_line(repo: Repo, entry: QuarantinedIdentifier, authors: dict[int, str], now: datetime) -> str:
    days = max((entry.expires_at - now).days, 0) if entry.expires_at is not None else 0
    who = authors.get(entry.created_by_id or 0, "someone")
    return (
        f"Quarantine expires in {days} days · {_escape_mrkdwn(entry.identifier)} ({entry.run_type})"
        f' · opened by {_escape_mrkdwn(who)} for "{_escape_mrkdwn(entry.reason)}"'
        f" · {_snapshot_url(repo, entry.run_type, entry.identifier)}"
    )


def _pileup_line(repo: Repo, run_type: str, identifier: str, count: int) -> str:
    return (
        f"{count} accepted variants of the current baseline · {_escape_mrkdwn(identifier)} ({run_type})"
        f" · {_snapshot_url(repo, run_type, identifier)}"
    )


def _display_names(user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return {
        user.id: user.first_name or user.email
        for user in User.objects.filter(id__in=user_ids).only("id", "first_name", "email")
    }


@frozen
class RunTypeAttribution:
    """What one run type can be attributed against today: a story index, or why there is none."""

    index: story_index.StoryIndex | None
    detail: str


def _attribution_sources(repo: Repo, run_types: set[str]) -> dict[str, RunTypeAttribution]:
    """Read the story index of the run behind the current baseline, for each run type in play.

    One artifact read per run type, not per item. A run type nothing owes today is never read, so a
    repo with no Storybook debt costs no download at all.
    """
    if not run_types:
        return {}
    newest_by_run_type = run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo.id))
    sources: dict[str, RunTypeAttribution] = {}
    for run_type in run_types:
        if run_type != RunType.STORYBOOK:
            sources[run_type] = RunTypeAttribution(index=None, detail=f"{run_type} runs are not supported yet")
            continue
        run = newest_by_run_type.get(run_type)
        if run is None:
            sources[run_type] = RunTypeAttribution(index=None, detail=_NO_BASELINE_RUN_DETAIL)
            continue
        github_run_id = (run.metadata or {}).get("github_run_id")
        if not isinstance(github_run_id, str) or not github_run_id:
            sources[run_type] = RunTypeAttribution(
                index=None, detail="the run behind the baseline records no workflow run"
            )
            continue
        index = story_index.fetch_story_index(repo, github_run_id)
        sources[run_type] = RunTypeAttribution(
            index=index,
            detail="" if index is not None else f"the Storybook build artifact for run {github_run_id} was not read",
        )
    return sources


def _attribution(sources: Mapping[str, RunTypeAttribution], run_type: str, identifier: str) -> Attribution:
    """Where one snapshot's story lives, or why the index cannot say."""
    source = sources.get(run_type)
    if source is None:
        return Attribution(kind=AttributionKind.UNAVAILABLE, detail=_NO_BASELINE_RUN_DETAIL)
    if source.index is None:
        return Attribution(kind=AttributionKind.UNAVAILABLE, detail=source.detail)
    path = story_index.story_path(source.index, identifier)
    if path is None:
        return Attribution(kind=AttributionKind.STORY_ABSENT)
    return Attribution(kind=AttributionKind.PLACED, source_path=path)


def collect_debt(repo: Repo, now: datetime) -> RepoDebt:
    """Evaluate both conditions against current data, attribute each item, and render its line."""
    expiring = quarantine.list_expiring_quarantines(repo.id, now=now)
    quarantined_keys = quarantine.active_quarantine_keys(repo.id, now=now)
    piled_up = {
        key: count
        for key, count in toleration.count_active_variants_against_current_baseline(repo.id, now=now).items()
        # Any live quarantine, expiring or not, already says somebody knows the snapshot is
        # unreliable, so asking them about the variants underneath it is a second reminder about
        # one problem.
        if count >= VARIANT_PILEUP_MIN and key not in quarantined_keys
    }

    run_types = {entry.run_type for entry in expiring} | {run_type for run_type, _ in piled_up}
    sources = _attribution_sources(repo, run_types)
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
                identifier=identifier,
                run_type=run_type,
                attribution=_attribution(sources, run_type, identifier),
                line=_pileup_line(repo, run_type, identifier, count),
            )
            for (run_type, identifier), count in sorted(piled_up.items(), key=lambda item: (-item[1], item[0]))
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


def _triage_reason(item: DebtItem) -> TriageReason:
    """Why an item nobody owns is in triage. A placed path with no owner needs an owners entry."""
    if item.attribution.kind == AttributionKind.PLACED:
        return TriageReason.UNOWNED_FILE
    if item.attribution.kind == AttributionKind.STORY_ABSENT:
        return TriageReason.STORY_ABSENT
    return TriageReason.UNAVAILABLE


def split_by_team(debt: RepoDebt, ownership: PathOwnership) -> list[TeamDigest]:
    """Group a repo's debt by the team that owns each item's story file.

    Everything else is triage rather than debt of the maintainers' own: it goes into the digest of
    the team that owns the product directory, grouped by why it has no owner. When that team is
    unowned too, the item is dropped with a log line rather than posted somewhere arbitrary.
    """
    fallback = ownership.team_by_path.get(_PRODUCT_PATH, UNOWNED_TEAM)
    expiring_by_team: dict[str, list[DebtItem]] = {}
    pileups_by_team: dict[str, list[DebtItem]] = {}
    triage_by_reason: dict[TriageReason, list[DebtItem]] = {}
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
            triage_by_reason.setdefault(_triage_reason(item), []).append(item)

    # Declaration order, so the three groups always read in the same order.
    triage = [
        TriageGroup(reason=reason, items=triage_by_reason[reason])
        for reason in TriageReason
        if reason in triage_by_reason
    ]
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
        {
            item.attribution.detail
            for group in digest.triage
            if group.reason == TriageReason.UNAVAILABLE
            for item in group.items
            if item.attribution.detail
        }
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
            f"{_escape_mrkdwn('; '.join(details))}. The digest tries again tomorrow."
        )
    return " ".join(sentences)


def _triage_line(item: DebtItem) -> str:
    """One triage item's line, carrying what its group's header asks the reader to act on."""
    if item.attribution.kind == AttributionKind.PLACED:
        return f"{item.line} · {_escape_mrkdwn(item.attribution.source_path)}"
    if item.attribution.kind == AttributionKind.UNAVAILABLE:
        return f"{item.line} · {_escape_mrkdwn(item.attribution.detail)}"
    return item.line


def thread_texts(digest: TeamDigest) -> list[str]:
    """The item lines, grouped by condition and then by triage reason, split to fit Slack's section cap."""
    lines = [
        *(item.line for item in digest.expiring_quarantines),
        *(item.line for item in digest.variant_pileups),
    ]
    for group in digest.triage:
        lines.append(_TRIAGE_HEADERS[group.reason])
        lines.extend(_triage_line(item) for item in group.items)
    lines.append(_FOOTER)
    messages: list[str] = []
    current: list[str] = []
    for line in lines:
        if current and len("\n".join([*current, line])) > _MAX_SECTION_CHARS:
            messages.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        messages.append("\n".join(current))
    return messages


def _blocks(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


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
    return Delivery(channel_id=match.channel.channel_id, channel_name=name, lead_prefix="")


def deliver(
    digest: TeamDigest,
    registry: Mapping[str, TeamEntry],
    channels_by_name: Mapping[str, SlackChannel],
    mode: str,
) -> Delivery | None:
    """Where this team's digest goes under the run's mode. None means nothing is posted."""
    resolved = resolve_channel(digest, registry, channels_by_name)
    if mode != MODE_SHADOW:
        return resolved
    shadow_channel = settings.VISUAL_REVIEW_DEBT_DIGEST_SHADOW_CHANNEL
    match = find_channel(channels_by_name, shadow_channel, allow_shared=False)
    if match.channel is None:
        logger.warning(
            "visual_review.debt_digest_shadow_channel_unusable",
            channel_name=shadow_channel,
            reason=match.reason,
        )
        return None
    return Delivery(
        channel_id=match.channel.channel_id,
        channel_name=shadow_channel.removeprefix("#"),
        # Names the channel the message would have gone to, so a reader of the shadow channel can
        # check the routing without re-deriving it.
        lead_prefix=(
            f"Shadow for #{resolved.channel_name}: " if resolved is not None else "Shadow, no channel resolved: "
        ),
    )


def send_debt_digest(repo: Repo, mode: str | None = None) -> list[str]:
    """Evaluate, attribute, and post one repo's digest. One team's failure does not stop the rest.

    Returns each team's rendered message, so an operator running this by hand can read what the
    run would send without reaching into the logs.
    """
    mode = mode or settings.VISUAL_REVIEW_DEBT_DIGEST_MODE
    if mode == MODE_OFF:
        return []

    debt = collect_debt(repo, timezone.now())
    if not debt.items:
        logger.info("visual_review.debt_digest_nothing_owed", repo_id=str(repo.id), team_id=repo.team_id)
        return []

    ownership = resolve_path_owners(repo.repo_full_name, paths_to_resolve(debt))
    digests = split_by_team(debt, ownership)

    integration: Integration | None = None
    channels_by_name: dict[str, SlackChannel] = {}
    if mode != MODE_PREVIEW:
        integration = Integration.objects.filter(team_id=repo.team_id, kind="slack").first()
        if integration is None:
            logger.info("visual_review.debt_digest_no_slack_integration", team_id=repo.team_id)
            return []
        channels_by_name = fetch_channel_map(integration)

    rendered: list[str] = []
    for digest in digests:
        try:
            rendered.append(_send_one(repo, digest, ownership.registry, channels_by_name, integration, mode))
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


def _send_one(
    repo: Repo,
    digest: TeamDigest,
    registry: Mapping[str, TeamEntry],
    channels_by_name: Mapping[str, SlackChannel],
    integration: Integration | None,
    mode: str,
) -> str:
    lead = lead_text(digest, repo)
    thread = thread_texts(digest)
    if mode == MODE_PREVIEW:
        resolved = resolve_channel(digest, registry, channels_by_name)
        rendered = "\n".join([lead, *thread])
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

    delivery = deliver(digest, registry, channels_by_name, mode)
    if delivery is None or integration is None:
        return ""

    slack = SlackIntegration(integration)
    lead = f"{delivery.lead_prefix}{lead}"
    try:
        thread_ts = post_with_join(slack, delivery.channel_id, _blocks(lead), lead, channel_name=delivery.channel_name)
    except SlackPostRefused as e:
        logger.warning("visual_review.debt_digest_post_refused", team_slug=digest.team_slug, error=str(e))
        return ""
    # Without a parent to hang them on, the item lines land in the channel as separate top-level
    # posts, which is the noise the thread exists to remove.
    if thread_ts is not None:
        for text in thread:
            post_message(slack, delivery.channel_id, _blocks(text), text, thread_ts=thread_ts)
    return "\n".join([lead, *thread])


def repos_in_scope() -> list[Repo]:
    """The repos the digest is configured for, by `owner/name`."""
    configured: Sequence[str] = settings.VISUAL_REVIEW_DEBT_DIGEST_REPOS
    if not configured:
        return []
    # nosemgrep: idor-lookup-without-team — cross-team beat sweep over a settings allowlist
    return list(Repo.objects.unscoped().filter(repo_full_name__in=list(configured)).order_by("created_at"))
