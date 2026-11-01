"""Highlights feed ranking from observation embeddings.

A consumer of the embedding worker's results ranks each observation once, from the vector the scan
already embeds for search, so the feed needs no model call and no sweep. Each vector is compared with fixed anchor sentences: the
closest issue anchor names the category, and its lead over the closest routine anchor is the score.
The feed turns scores into a percentile within each scanner when it loads, so a scanner that sees
errors all the time does not fill the feed.
"""

import math
import asyncio
from collections import Counter
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, Literal

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.db.models.functions import Coalesce

import numpy as np
from asgiref.sync import sync_to_async

from posthog.api.embedding_worker import async_generate_embedding
from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.embeddings import OBSERVATION_EMBEDDING_MODEL
from products.replay_vision.backend.highlight_builds import RankedEntry, rank_window, stored_generation
from products.replay_vision.backend.highlight_feed import HIGHLIGHT_FEED_MIN_ITEMS, HighlightFeedEntry, finish_feed
from products.replay_vision.backend.models.replay_highlight_feed import ReplayHighlightFeedEntry
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.models.replay_observation_rank import ReplayObservationRank
from products.replay_vision.backend.models.replay_observation_view import ReplayObservationView
from products.replay_vision.backend.observation_ranks import CATEGORY_CODES, CATEGORY_NAMES, NewRank, record_ranks
from products.replay_vision.backend.scanner_access import accessible_observations, readable_experiment_ids

WatchCategory = Literal["failure", "struggle", "revenue", "routine"]

# Bump when an anchor changes: scores from different anchor sets do not compare, so the feed
# ignores ranks written under another version until they age out of the window.
ANCHOR_VERSION = 1

# Each sentence keeps its key for good: stored similarities and a viewer's anchor choices refer to anchors by key.
ANCHORS: dict[WatchCategory, dict[str, str]] = {
    "failure": {
        "error_message": "The user saw an error message and the action they tried failed.",
        "request_failed": "A request failed or the page crashed, showing an error to the user.",
        "silent_click": "The user clicked a button and nothing happened; the action silently did not work.",
        "endless_spinner": "The page got stuck loading and the user waited on a spinner that never finished.",
        "dead_end": "The user was blocked by a dead end, a 404 page, or an access denied message.",
    },
    "struggle": {
        "repeated_action": "The user repeated the same action several times because it did not give the result they expected.",
        "rage_click": "The user rage clicked and gave up on the task without finishing.",
        "form_abandoned": "The user hit a validation error or confusing state in a form and abandoned it.",
        "stuck_trying": "The user was stuck: they tried several different ways to do one thing and none worked.",
        "workaround": "The user worked around a broken or missing feature to get their task done.",
    },
    "revenue": {
        "cancel_or_downgrade": "The user went to billing to cancel their subscription or downgrade their plan.",
        "payment_failed": "The user tried to upgrade or pay but the upgrade or payment failed.",
        "usage_limit": "The user hit a usage limit that stopped a feature from working.",
        "frustrated_support": "The user contacted support frustrated about a problem.",
    },
    "routine": {
        "completed_task": "The user browsed normally and completed what they came to do without any issues.",
        "nothing_notable": "A routine session with nothing notable: normal navigation and expected behavior.",
        "few_pages": "The user viewed a few pages and left; nothing went wrong.",
        "nothing_stands_out": "Nothing stands out in this session.",
        "no_friction": "Routine session with no errors or friction; the user did what they intended.",
        "pricing_docs": "The user browsed the pricing page and documentation normally.",
        "task_success": "The user successfully completed the task without problems.",
        "exploring_site": "The user explored different sections of the website to learn about the product.",
        "reading_docs": "The user read through a product or documentation page.",
        "reviewing_list": "The user looked through a list and opened a few items to review them.",
        "left_early": "The user started something and left before finishing, with no sign of a problem.",
        "never_reached": "The user never reached the part of the product this check is about.",
    },
}
ISSUE_CATEGORIES: tuple[WatchCategory, ...] = ("failure", "struggle", "revenue")

# Struggle picks rated worth watching less often than failure and revenue picks in a blind rating.
CATEGORY_WEIGHT: dict[str, float] = {"failure": 1.0, "revenue": 1.0, "struggle": 0.85}

# The feed surfaces a scanner's top fifth by score, once the scanner has enough ranked rows to
# make a percentile mean something.
HIGHLIGHT_PICK_MIN_PERCENTILE = 0.8
HIGHLIGHT_PICK_MIN_SCANNER_ROWS = 10
HIGHLIGHT_PICK_SEEN_PENALTY = 0.3
# Each earlier impression keeps this share of a pick's score, so a pick shown three times without a
# click sinks below a fresh one.
HIGHLIGHT_PICK_IMPRESSION_DECAY = 0.8
# A pick's score grows by this factor times the log of the people its group reached, up to the cap, so a problem
# that hit six people outranks an equally strong one-off without burying everything else.
HIGHLIGHT_PICK_PEOPLE_BOOST = 0.25
HIGHLIGHT_PICK_PEOPLE_BOOST_CAP = 2.0
# Copies of one finding the feed keeps per group, so a viewed or restricted top copy does not hide the group.
HIGHLIGHT_PICK_GROUP_CANDIDATES = 3
# How much wider the second pick fetch reads when the first is all copies of a few feed groups.
HIGHLIGHT_PICK_REFILL_FACTOR = 10

_ANCHOR_CACHE_TTL_S = 7 * 24 * 3600


@frozen
class WatchRank:
    category: WatchCategory
    contrast: float


@frozen
class AnchorReading:
    rank: WatchRank
    similarities: dict[str, float]


_ANCHOR_CACHE_KEY = f"replay-vision:watch-rank-anchors:v{ANCHOR_VERSION}:{OBSERVATION_EMBEDDING_MODEL.value}"


def normalize(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.linalg.norm(matrix, axis=-1, keepdims=True)


# The anchors never change within a version, so each process keeps them after the first read.
_anchors_in_process: dict[WatchCategory, np.ndarray] | None = None


async def anchor_vectors(team_id: int) -> dict[WatchCategory, np.ndarray]:
    """Unit vectors for every anchor, embedded once and cached across teams.

    Embedded under the calling team because the worker gates every call on a team's AI opt-in, and
    a team that ranks observations has already passed that gate.
    """
    global _anchors_in_process
    if _anchors_in_process is None:
        _anchors_in_process = await _load_anchor_vectors(team_id)
    return _anchors_in_process


async def _load_anchor_vectors(team_id: int) -> dict[WatchCategory, np.ndarray]:
    vectors: dict[WatchCategory, list[list[float]]] | None = await cache.aget(_ANCHOR_CACHE_KEY)
    if vectors is None:
        team = await Team.objects.aget(id=team_id)
        embedded = await asyncio.gather(
            *(
                async_generate_embedding(team, text, model=OBSERVATION_EMBEDDING_MODEL.value)
                for texts in ANCHORS.values()
                for text in texts.values()
            )
        )
        rows = iter(response.embedding for response in embedded)
        vectors = {category: [next(rows) for _ in texts] for category, texts in ANCHORS.items()}
        await cache.aset(_ANCHOR_CACHE_KEY, vectors, _ANCHOR_CACHE_TTL_S)
    anchors = {category: normalize(np.array(rows, dtype=float)) for category, rows in vectors.items()}
    return anchors


def classify(vector: list[float] | np.ndarray, anchors: dict[WatchCategory, np.ndarray]) -> AnchorReading:
    """The closest issue category and its lead over the closest routine anchor, given unit anchors.

    A negative lead means the observation reads more like routine than like any issue, and the
    category is then routine.
    """
    unit = normalize(np.asarray(vector, dtype=float))
    by_category = {category: anchors[category] @ unit for category in ANCHORS}
    closest = {category: float(np.max(sims)) for category, sims in by_category.items()}
    category = max(ISSUE_CATEGORIES, key=lambda c: closest[c])
    contrast = round(closest[category] - closest["routine"], 4)
    rank = WatchRank(
        category=category if contrast > 0 else "routine",
        contrast=contrast,
    )
    similarities = {
        key: round(float(sim), 4) for c, sims in by_category.items() for key, sim in zip(ANCHORS[c], sims, strict=True)
    }
    return AnchorReading(rank=rank, similarities=similarities)


def save_anchor_similarities(team_id: int, similarities: dict[str, dict[str, float]]) -> None:
    # A bulk insert skips the model's canonical-team rewrite, so the row carries the id reads are scoped to.
    canonical_team_id = resolve_effective_team_id(team_id)
    ReplayObservationAnchorSimilarity.objects.for_team(canonical_team_id, canonical=True).bulk_create(
        [
            ReplayObservationAnchorSimilarity(
                observation_id=observation_id,
                team_id=canonical_team_id,
                anchor_version=ANCHOR_VERSION,
                similarities=values,
            )
            for observation_id, values in similarities.items()
        ],
        update_conflicts=True,
        unique_fields=["observation"],
        update_fields=["anchor_version", "similarities"],
    )


@frozen
class RankRequest:
    team_id: int
    scanner_id: str
    observation_id: str
    vector: list[float]


async def rank_observation(request: RankRequest) -> Literal["ranked", "already_ranked", "missing"]:
    """Rank one observation from its embedding and save its rank row, unless it has one under the current anchors.

    Keeping an existing rank makes a redelivered result harmless, and keeps the feed group and search theme
    written next to it.
    """
    observation = await (
        ReplayObservation.objects.filter(team_id=request.team_id, id=request.observation_id).values("id").afirst()
    )
    # A deleted observation, or a deleted team, leaves nothing to rank.
    if observation is None:
        return "missing"
    # The scoped manager resolves the team synchronously, so the check runs off the event loop.
    if await sync_to_async(_has_current_rank)(request.team_id, request.observation_id):
        return "already_ranked"
    reading = classify(request.vector, await anchor_vectors(request.team_id))
    written = await sync_to_async(_save_rank)(request.team_id, request.observation_id, reading)
    return "ranked" if written else "already_ranked"


def _save_rank(team_id: int, observation_id: str, reading: AnchorReading) -> bool:
    # One transaction, so a rank row always comes with its similarities.
    rank = NewRank(contrast=reading.rank.contrast, category=reading.rank.category)
    with transaction.atomic():
        save_anchor_similarities(team_id, {observation_id: reading.similarities})
        return record_ranks(team_id, ANCHOR_VERSION, {observation_id: rank}) > 0


def _has_current_rank(team_id: int, observation_id: str) -> bool:
    return current_ranks(team_id).filter(observation_id=observation_id).exists()


def current_ranks(team_id: int) -> QuerySet[ReplayObservationRank]:
    """The team's rank rows written under the current anchors."""
    return ReplayObservationRank.objects.for_team(team_id).filter(anchor_version=ANCHOR_VERSION)


def people_boost(people: int) -> float:
    """How much a pick's score grows with the number of people its feed group reached."""
    return min(HIGHLIGHT_PICK_PEOPLE_BOOST_CAP, 1 + HIGHLIGHT_PICK_PEOPLE_BOOST * math.log(max(people, 1)))


def _cap_feed_groups(rows: list[dict[str, Any]], cap: int) -> dict[Any, dict[str, Any]]:
    """The first `cap` rows by observation id, keeping a few per feed group so the ranker can still pick a readable,
    unseen one. A group never spans scanners, so pick order meets each group's rows best first."""
    picked: dict[Any, dict[str, Any]] = {}
    group_rows: Counter[Any] = Counter()
    for row in rows:
        if group_rows[row["group_root"]] >= HIGHLIGHT_PICK_GROUP_CANDIDATES:
            continue
        group_rows[row["group_root"]] += 1
        picked[row["observation_id"]] = row
        if len(picked) >= cap:
            break
    return picked


def _stored_window_entries(
    team_id: int,
    generation: int,
    window_days: int,
    start: datetime,
    scanner_ids: Sequence[Any],
    categories: Sequence[str],
    experiment_ids: Collection[int],
    dismissed_ids: Collection[Any],
    limit: int,
) -> list[dict[str, Any]]:
    entries = (
        ReplayHighlightFeedEntry.objects.for_team(team_id)
        .filter(
            generation=generation,
            window_days=window_days,
            # A build ranked before this load's window moved on can hold rows that have since left it.
            created_at__gte=start,
            scanner_id__in=list(scanner_ids),
            category__in=[CATEGORY_CODES[category] for category in categories],
            experiment_id__in=[0, *experiment_ids],
        )
        .exclude(observation_id__in=list(dismissed_ids))
        .order_by("place", "-percentile", "-created_at", "-observation_id")
        .values(*_ENTRY_FIELDS)[:limit]
    )
    return list(entries)


def _ranked_window_entries(
    entries: list[RankedEntry],
    scanner_ids: Sequence[Any],
    categories: Sequence[str],
    experiment_ids: Collection[int],
    dismissed_ids: Collection[Any],
    limit: int,
) -> list[dict[str, Any]]:
    scanners = {str(scanner_id) for scanner_id in scanner_ids}
    codes = {CATEGORY_CODES[category] for category in categories}
    readable = {0, *experiment_ids}
    dismissed = {str(observation_id) for observation_id in dismissed_ids}
    kept = [
        entry
        for entry in entries
        if str(entry.scanner_id) in scanners
        and entry.category in codes
        and entry.experiment_id in readable
        and str(entry.observation_id) not in dismissed
    ]
    kept.sort(
        key=lambda entry: (-entry.place, entry.percentile, entry.created_at, str(entry.observation_id)), reverse=True
    )
    return [{field: getattr(entry, field) for field in _ENTRY_FIELDS} for entry in kept[:limit]]


_ENTRY_FIELDS = (
    "observation_id",
    "scanner_id",
    "created_at",
    "category",
    "percentile",
    "group_root",
    "person_key",
)


@frozen
class FeedWindow:
    """The window a feed load ranks: a preset window read from the team's stored build, or any other range ranked on
    the spot the same way."""

    start: datetime
    end: datetime
    as_of: datetime
    window_days: int | None
    generation: int | None


def feed_window(team_id: int, start: datetime, end: datetime, as_of: datetime, preset_days: int | None) -> FeedWindow:
    """The feed's window from `start` to `end`. A preset window reads the team's stored build."""
    generation = stored_generation(team_id, ANCHOR_VERSION, as_of) if preset_days is not None else None
    if generation is None:
        return FeedWindow(start=start, end=end, as_of=as_of, window_days=None, generation=None)
    return FeedWindow(start=start, end=end, as_of=as_of, window_days=preset_days, generation=generation)


@frozen
class GroupReach:
    sessions: int
    people: int


def _group_reach(
    team_id: int,
    window: FeedWindow,
    roots: Collection[Any],
    scanner_ids: Sequence[Any],
    categories: Sequence[str],
    experiment_ids: Collection[int],
) -> dict[str, GroupReach]:
    """Sessions and distinct people in each feed group, counted over the window's rows the viewer may read in the
    chosen categories, so a card's counts match the group list it opens."""
    root_ids = list(roots)
    members = (
        current_ranks(team_id)
        .filter(Q(feed_group_id__in=root_ids) | Q(observation_id__in=root_ids, feed_group_id__isnull=True))
        .filter(
            ranked_at__lte=window.as_of,
            created_at__gte=window.start,
            created_at__lte=window.end,
            scanner_id__in=list(scanner_ids),
            category__in=[CATEGORY_CODES[category] for category in categories],
            experiment_id__in=[0, *experiment_ids],
        )
        .values(root=Coalesce("feed_group_id", "observation_id"))
        .annotate(sessions=Count("observation_id"), people=Count("person_key", distinct=True))
    )
    return {str(row["root"]): GroupReach(sessions=row["sessions"], people=row["people"]) for row in members}


def views_by(viewer_id: int, as_of: datetime) -> QuerySet[ReplayObservationView]:
    """The viewer's observation views up to `as_of`, so later views wait for the next feed load."""
    return ReplayObservationView.objects.filter(user_id=viewer_id, created_at__lte=as_of)


def select_embedding_picks(
    window: FeedWindow,
    scanner_ids: Sequence[Any],
    viewer_id: int,
    access: UserAccessControl,
    team_id: int,
    cap: int,
    categories: Sequence[str],
    dismissed_ids: Collection[Any],
) -> list[dict[str, Any]]:
    """The window's pick rows for the embedding ranker, each with its percentile and its feed group's reach.

    A row's percentile is taken over every ranked row its scanner has in the window, so a longer window reaches further
    back instead of re-ranking the same newest rows. `categories` narrows the picks after ranking, so turning a
    category off drops its rows without promoting weaker rows of the others.
    """
    experiment_ids = readable_experiment_ids(access, team_id)
    # Bounds the fetch; a window full of copies of a few findings reads a wider slice once.
    fetch_limit = cap * (HIGHLIGHT_PICK_GROUP_CANDIDATES + 1)
    ranked = (
        rank_window(team_id, ANCHOR_VERSION, window.start, window.end, scanner_ids, ranked_before=window.as_of)
        if window.window_days is None or window.generation is None
        else None
    )

    def window_rows(limit: int) -> list[dict[str, Any]]:
        if ranked is not None:
            return _ranked_window_entries(ranked, scanner_ids, categories, experiment_ids, dismissed_ids, limit)
        assert window.window_days is not None and window.generation is not None
        return _stored_window_entries(
            team_id,
            window.generation,
            window.window_days,
            window.start,
            scanner_ids,
            categories,
            experiment_ids,
            dismissed_ids,
            limit,
        )

    rows = window_rows(fetch_limit)
    window_values = _cap_feed_groups(rows, cap)
    if len(window_values) < cap and len(rows) == fetch_limit:
        window_values = _cap_feed_groups(window_rows(fetch_limit * HIGHLIGHT_PICK_REFILL_FACTOR), cap)
    # The entries carry everything ranking reads, so only ids load here, and the endpoint gates its page's rows on
    # experiment access. A stored entry outlives a deleted observation until its feed rebuilds.
    live = set(
        ReplayObservation.objects.filter(team_id=team_id, id__in=list(window_values)).values_list("id", flat=True)
    )
    window_values = {observation_id: entry for observation_id, entry in window_values.items() if observation_id in live}
    if not window_values:
        return []
    viewed = set(
        views_by(viewer_id, window.as_of)
        .filter(observation_id__in=list(window_values))
        .values_list("observation_id", flat=True)
    )
    roots = {entry["group_root"] for entry in window_values.values()}
    reach = _group_reach(team_id, window, roots, scanner_ids, categories, experiment_ids)
    picks: list[dict[str, Any]] = []
    for observation_id, entry in window_values.items():
        group = reach.get(str(entry["group_root"]), GroupReach(sessions=1, people=1))
        picks.append(
            {
                "id": observation_id,
                "scanner_id": entry["scanner_id"],
                "created_at": entry["created_at"],
                "person_key": entry["person_key"],
                "feed_viewed": observation_id in viewed,
                "watch_category": CATEGORY_NAMES[entry["category"]],
                "watch_percentile": entry["percentile"],
                "watch_group_root": str(entry["group_root"]),
                "watch_group_size": group.sessions,
                "watch_group_people": group.people,
            }
        )
    return picks


def select_embedding_filler(
    walkable: QuerySet[ReplayObservation],
    scanner_ids: list[Any],
    viewed: Exists,
    access: UserAccessControl,
    team_id: int,
    pick_roots: set[str],
    hidden_categories: Sequence[str],
) -> list[dict[str, Any]]:
    """The newest readable rows outside the picks' feed groups, unwatched first, enough to bring a thin feed up to
    its floor."""
    ranks = ReplayObservationRank.objects.for_team(team_id).filter(observation_id=OuterRef("id"))
    roots = list(pick_roots)
    base = (
        accessible_observations(access, team_id, walkable.filter(scanner_id__in=scanner_ids))
        .exclude(id__in=roots)
        .exclude(
            Exists(
                ranks.filter(
                    Q(feed_group_id__in=roots)
                    | Q(category__in=[CATEGORY_CODES[category] for category in hidden_categories])
                )
            )
        )
        .annotate(feed_viewed=viewed)
    )
    fields = ("id", "scanner_id", "created_at", "feed_viewed")
    # Two short newest-first walks, instead of ordering by the viewed flag, which would sort the whole window.
    rows = list(
        base.filter(feed_viewed=False).order_by("-created_at", "-id").values(*fields)[:HIGHLIGHT_FEED_MIN_ITEMS]
    )
    if len(rows) < HIGHLIGHT_FEED_MIN_ITEMS:
        rows += list(
            base.filter(feed_viewed=True)
            .order_by("-created_at", "-id")
            .values(*fields)[: HIGHLIGHT_FEED_MIN_ITEMS - len(rows)]
        )
    return rows


def rank_highlight_feed_by_embedding(rows: list[dict[str, Any]]) -> list[HighlightFeedEntry]:
    """Rank candidate rows (`id`, `scanner_id`, `created_at`, `feed_viewed`, optionally `feed_impressions`, and for
    picks `person_key` and the `watch_*` fields `select_embedding_picks` adds).

    A pick is a row with a percentile whose category is an issue. Rows of one feed group collapse to their best-scoring
    row, which carries the size of the group. Picks sort by weighted percentile, decayed for each earlier impression,
    viewed rows docked, one scanner held to a share of the picks, and one person's picks spaced apart. Every other row
    is filler, kept only to reach the feed's floor.
    """
    best_in_group: dict[str, tuple[float, dict[str, Any]]] = {}
    group_members: dict[str, list[str]] = {}
    for row in rows:
        percentile = row.get("watch_percentile")
        if percentile is None or row.get("watch_category") not in ISSUE_CATEGORIES:
            continue
        # Group before the cutoff, so members below it still count toward the group and never return as filler.
        group = row["watch_group_root"]
        group_members.setdefault(group, []).append(str(row["id"]))
        # Only a member above the cutoff can stand for the group, so the seen penalty never disqualifies it.
        if percentile < HIGHLIGHT_PICK_MIN_PERCENTILE:
            continue
        score = (
            percentile
            * CATEGORY_WEIGHT[row["watch_category"]]
            * people_boost(row.get("watch_group_people") or 1)
            * HIGHLIGHT_PICK_IMPRESSION_DECAY ** row.get("feed_impressions", 0)
        )
        if row.get("feed_viewed"):
            score -= HIGHLIGHT_PICK_SEEN_PENALTY
        if group not in best_in_group or score > best_in_group[group][0]:
            best_in_group[group] = (score, row)
    grouped_ids = {member for group in best_in_group for member in group_members[group]}

    picks: list[tuple[float, Any, Any, HighlightFeedEntry]] = []
    for group, (score, row) in best_in_group.items():
        reason = {
            "kind": "embedding_pick",
            "watch_category": row["watch_category"],
            "similar_count": max(len(group_members[group]), row.get("watch_group_size") or 0) - 1,
            "affected_people": row.get("watch_group_people") or 1,
        }
        picks.append(
            (
                score,
                row["created_at"],
                row.get("scanner_id"),
                HighlightFeedEntry(observation_id=row["id"], reason=reason, person_key=row.get("person_key")),
            )
        )
    # A pick stands for its whole feed group, so no member returns as filler.
    return finish_feed(picks, [row for row in rows if str(row["id"]) not in grouped_ids])
