"""What to watch ranking from observation embeddings.

A consumer of the embedding worker's results ranks each observation once, from the vector the scan
already embeds for search, so the feed needs no model call and no sweep. Each vector is compared with fixed anchor sentences: the
closest issue anchor names the category, and its lead over the closest routine anchor is the score.
The feed turns scores into a percentile within each scanner when it loads, so a scanner that sees
errors all the time does not fill the feed.
"""

import math
import asyncio
from collections import Counter
from dataclasses import asdict
from typing import Any, Literal

from django.core.cache import cache
from django.core.exceptions import EmptyResultSet
from django.db import connections
from django.db.models import CharField, Count, Exists, F, QuerySet, Value, Window
from django.db.models.expressions import RawSQL
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Coalesce, NullIf, RowNumber

import numpy as np

from posthog.api.embedding_worker import async_generate_embedding
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.utils import dict_from_cursor_fetchall

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.embeddings import OBSERVATION_EMBEDDING_MODEL
from products.replay_vision.backend.models.replay_observation import (
    ReplayObservation,
    jsonb_typeof,
    watch_group_root,
    watch_rank_contrast,
)
from products.replay_vision.backend.models.replay_observation_anchor_similarity import ReplayObservationAnchorSimilarity
from products.replay_vision.backend.scanner_access import accessible_observations
from products.replay_vision.backend.watch_feed import WATCH_FEED_MIN_ITEMS, WatchFeedEntry, finish_feed

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
WATCH_PICK_MIN_PERCENTILE = 0.8
WATCH_PICK_MIN_SCANNER_ROWS = 10
WATCH_PICK_SEEN_PENALTY = 0.3
# Each earlier impression keeps this share of a pick's score, so a pick shown three times without a
# click sinks below a fresh one.
WATCH_PICK_IMPRESSION_DECAY = 0.8
# A pick's score grows by this factor times the log of the people its group reached, up to the cap, so a problem
# that hit six people outranks an equally strong one-off without burying everything else.
WATCH_PICK_PEOPLE_BOOST = 0.25
WATCH_PICK_PEOPLE_BOOST_CAP = 2.0
# Copies of one finding the pick query keeps, so a viewed or restricted top copy does not hide the group.
WATCH_PICK_GROUP_CANDIDATES = 3

_ANCHOR_CACHE_TTL_S = 7 * 24 * 3600


@frozen
class WatchRank:
    category: WatchCategory
    contrast: float
    # The closest anchor's similarity per category, so a viewer's choice of categories can be scored from the row.
    scores: dict[str, float]
    anchor_version: int = ANCHOR_VERSION

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


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
        scores={c: round(score, 4) for c, score in closest.items()},
    )
    similarities = {
        key: round(float(sim), 4) for c, sims in by_category.items() for key, sim in zip(ANCHORS[c], sims, strict=True)
    }
    return AnchorReading(rank=rank, similarities=similarities)


def current_rank(row: dict[str, Any]) -> dict[str, Any] | None:
    """The row's rank when it comes from the current anchors, else None."""
    rank = row.get("watch_rank")
    if not isinstance(rank, dict) or rank.get("anchor_version") != ANCHOR_VERSION:
        return None
    contrast = rank.get("contrast")
    if not isinstance(contrast, int | float) or isinstance(contrast, bool):
        return None
    return rank


async def save_anchor_similarities(team_id: int, similarities: dict[str, dict[str, float]]) -> None:
    await ReplayObservationAnchorSimilarity.objects.abulk_create(
        [
            ReplayObservationAnchorSimilarity(
                observation_id=observation_id, team_id=team_id, anchor_version=ANCHOR_VERSION, similarities=values
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
    """Rank one observation from its embedding and save the rank on the row, unless it has a current one.

    Keeping an existing rank makes a redelivered result harmless, and keeps the feed group and search theme
    written next to it.
    """
    row = await (
        ReplayObservation.objects.filter(team_id=request.team_id, id=request.observation_id)
        .values("watch_rank")
        .afirst()
    )
    # A deleted observation, or a deleted team, leaves nothing to rank.
    if row is None:
        return "missing"
    if current_rank({"watch_rank": row["watch_rank"]}) is not None:
        return "already_ranked"
    reading = classify(request.vector, await anchor_vectors(request.team_id))
    # The similarities land first, so a rank on the row means its similarities are there too.
    await save_anchor_similarities(request.team_id, {request.observation_id: reading.similarities})
    await ReplayObservation.objects.filter(team_id=request.team_id, id=request.observation_id).aupdate(
        watch_rank=reading.rank.to_json()
    )
    return "ranked"


def _scanner_percentiles(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Each ranked row's score as a percentile among its scanner's ranked rows in the window."""
    by_scanner: dict[Any, list[tuple[float, str]]] = {}
    for row in rows:
        if rank := current_rank(row):
            by_scanner.setdefault(row["scanner_id"], []).append((float(rank["contrast"]), str(row["id"])))
    percentiles: dict[str, float] = {}
    for scored in by_scanner.values():
        if len(scored) < WATCH_PICK_MIN_SCANNER_ROWS:
            continue
        scored.sort()
        for position, (_, observation_id) in enumerate(scored):
            percentiles[observation_id] = (position + 0.5) / len(scored)
    return percentiles


def people_boost(people: int) -> float:
    """How much a pick's score grows with the number of people its feed group reached."""
    return min(WATCH_PICK_PEOPLE_BOOST_CAP, 1 + WATCH_PICK_PEOPLE_BOOST * math.log(max(people, 1)))


def _cap_feed_groups(rows: list[dict[str, Any]], cap: int) -> dict[Any, dict[str, Any]]:
    """The first `cap` rows, keeping a few per feed group so the ranker can still pick a readable, unseen one.

    A group never spans scanners, so the pick order meets each group's rows best first.
    """
    picked: dict[Any, dict[str, Any]] = {}
    group_rows: Counter[str] = Counter()
    for row in rows:
        if group_rows[row["watch_group_root"]] >= WATCH_PICK_GROUP_CANDIDATES:
            continue
        group_rows[row["watch_group_root"]] += 1
        picked[row["id"]] = row
        if len(picked) >= cap:
            break
    return picked


def _pick_window_rows(
    ranked: QuerySet[ReplayObservation], current_ranks: QuerySet[ReplayObservation], limit: int | None
) -> list[dict[str, Any]]:
    """Each scanner's top-fifth issue rows in pick order: every scanner's best first, then every second-best.

    A row's percentile needs only its rank from the top and its scanner's row count, so the query counts each
    scanner on a narrow index and then reads just its top fifth by score, instead of sorting the whole window.
    """
    contrast = watch_rank_contrast()
    scanner_counts = (
        ranked.values("scanner_id")
        .annotate(scanner_rows=Count("id"))
        .filter(scanner_rows__gte=WATCH_PICK_MIN_SCANNER_ROWS)
        .values("scanner_id", "scanner_rows")
    )
    scanner_top = (
        # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (a fixed column reference to the CTE below)
        current_ranks.filter(scanner_id=RawSQL('"scanner_counts"."scanner_id"', ()))
        .annotate(
            scanner_rank=Window(RowNumber(), order_by=[contrast.desc(), F("id").desc()]),
            watch_group_root=watch_group_root(),
            pick_category=F("watch_category"),
        )
        .order_by(contrast.desc(), "-id")
        .values("id", "created_at", "scanner_rank", "watch_group_root", "pick_category")
    )
    try:
        counts_sql, counts_params = scanner_counts.query.sql_with_params()
        top_sql, top_params = scanner_top.query.sql_with_params()
    except EmptyResultSet:
        # Django compiles a filter that can match nothing, such as an empty scanner list, to this.
        return []
    # Only fragments written here join the compiled ORM SQL; every value travels as a parameter.
    sql = f"""
        WITH scanner_counts AS ({counts_sql})
        SELECT id, watch_percentile, watch_group_root FROM (
            SELECT scanner_top.*,
                ((scanner_counts.scanner_rows - scanner_top.scanner_rank + 1) - 0.5)
                    / scanner_counts.scanner_rows::double precision AS watch_percentile
            FROM scanner_counts
            CROSS JOIN LATERAL ({top_sql} LIMIT floor(scanner_counts.scanner_rows * %s)::int + 1) scanner_top
        ) picks
        WHERE pick_category = ANY(%s) AND watch_percentile >= %s
        ORDER BY scanner_rank, watch_percentile DESC, created_at DESC, id DESC
        LIMIT %s
    """
    params = (
        *counts_params,
        *top_params,
        1 - WATCH_PICK_MIN_PERCENTILE,
        list(ISSUE_CATEGORIES),
        WATCH_PICK_MIN_PERCENTILE,
        limit,
    )
    with connections[ranked.db].cursor() as cursor:
        cursor.execute(sql, params)
        return dict_from_cursor_fetchall(cursor)


def select_embedding_picks(
    walkable: QuerySet[ReplayObservation],
    scanner_ids: list[Any],
    viewed: Exists,
    access: UserAccessControl,
    team_id: int,
    cap: int,
) -> list[dict[str, Any]]:
    """The window's pick rows for the embedding ranker, with each row's percentile and the reach of its feed group.

    The percentile is taken over every ranked row a scanner has in the window, not over a recency slice, so a
    longer window reaches further back instead of re-ranking the same newest rows.
    """
    group_root = watch_group_root()
    ranked = walkable.filter(
        # The explicit null and anchor checks let Postgres match the partial `rlo_ranked_*` indexes.
        scanner_id__in=scanner_ids,
        watch_rank__isnull=False,
        watch_rank__anchor_version=ANCHOR_VERSION,
    )
    current_ranks = ranked.alias(
        watch_category=KeyTextTransform("category", "watch_rank"),
        contrast_type=jsonb_typeof(KeyTransform("contrast", "watch_rank")),
    ).filter(contrast_type="number")
    # Bounds the fetch, since a client-side cursor buffers every row; only a window full of copies needs the rest.
    fetch_limit = cap * (WATCH_PICK_GROUP_CANDIDATES + 1)
    rows = _pick_window_rows(ranked, current_ranks, fetch_limit)
    window_values = _cap_feed_groups(rows, cap)
    if len(window_values) < cap and len(rows) == fetch_limit:
        window_values = _cap_feed_groups(_pick_window_rows(ranked, current_ranks, None), cap)
    if not window_values:
        return []
    # Counted over readable rows only, so a group never reveals how many restricted sessions it holds. Members
    # below the cutoff still count, and a person who hit the problem twice counts once.
    person = Coalesce(NullIf("distinct_id", Value("")), "session_id", output_field=CharField())
    roots = {row["watch_group_root"] for row in window_values.values()}
    group_reach = {
        row["watch_group_root"]: row
        for row in accessible_observations(
            access,
            team_id,
            # Matches the picks' groups on the indexed group root first, so only their members reach the snapshot gate.
            current_ranks.alias(member_root=group_root).filter(
                member_root__in=list(roots), watch_category__in=ISSUE_CATEGORIES
            ),
        )
        .annotate(watch_group_root=group_root)
        .values("watch_group_root")
        .annotate(sessions=Count("id"), people=Count(person, distinct=True))
    }
    # The row-gate reads each row's snapshot JSON, so it runs on the picks only.
    rows = list(
        accessible_observations(
            access, team_id, ReplayObservation.objects.filter(team_id=team_id, id__in=list(window_values))
        )
        .annotate(feed_viewed=viewed)
        .values("id", "scanner_id", "session_id", "created_at", "watch_rank", "feed_viewed")
    )
    for row in rows:
        window = window_values[row["id"]]
        reach = group_reach.get(window["watch_group_root"], {})
        row["watch_percentile"] = window["watch_percentile"]
        row["watch_group_root"] = window["watch_group_root"]
        row["watch_group_size"] = reach.get("sessions", 1)
        row["watch_group_people"] = reach.get("people", 1)
    return rows


def select_embedding_filler(
    walkable: QuerySet[ReplayObservation],
    scanner_ids: list[Any],
    viewed: Exists,
    access: UserAccessControl,
    team_id: int,
    pick_roots: set[str],
) -> list[dict[str, Any]]:
    """The newest readable rows outside the picks' feed groups, unwatched first, enough to bring a thin feed up to its floor."""
    base = (
        accessible_observations(access, team_id, walkable.filter(scanner_id__in=scanner_ids))
        .annotate(watch_group_root=watch_group_root())
        .exclude(watch_group_root__in=pick_roots)
        .annotate(feed_viewed=viewed)
    )
    fields = ("id", "scanner_id", "session_id", "created_at", "watch_rank", "feed_viewed")
    # Two short newest-first walks, because ordering by the viewed flag would sort the whole window.
    rows = list(base.filter(feed_viewed=False).order_by("-created_at", "-id").values(*fields)[:WATCH_FEED_MIN_ITEMS])
    if len(rows) < WATCH_FEED_MIN_ITEMS:
        rows += list(
            base.filter(feed_viewed=True)
            .order_by("-created_at", "-id")
            .values(*fields)[: WATCH_FEED_MIN_ITEMS - len(rows)]
        )
    return rows


def rank_watch_feed_by_embedding(rows: list[dict[str, Any]]) -> list[WatchFeedEntry]:
    """Rank candidate rows (`id`, `scanner_id`, `session_id`, `created_at`, `watch_rank`, `feed_viewed`,
    and optionally `feed_impressions`) on the embedding rank the watch rank consumer wrote.

    A pick is a row in its scanner's top fifth by score whose category is an issue. Rows of one feed group
    collapse to their best-scoring row, which carries the size of the group. Picks sort by weighted
    percentile, decayed for each earlier impression, viewed rows docked, one scanner held to a share
    of the picks, and one session's picks spaced apart. Every other row is filler, trimmed to the same
    floor as the other rankers.
    """
    # Rows from `select_embedding_picks` carry their whole-window percentile; a plain candidate slice does not.
    percentiles = (
        {str(row["id"]): row["watch_percentile"] for row in rows if row.get("watch_percentile") is not None}
        if any("watch_percentile" in row for row in rows)
        else _scanner_percentiles(rows)
    )
    best_in_group: dict[str, tuple[float, dict[str, Any]]] = {}
    group_members: dict[str, list[str]] = {}
    for row in rows:
        rank = current_rank(row)
        observation_id = str(row["id"])
        percentile = percentiles.get(observation_id)
        if rank is None or percentile is None or rank.get("category") not in ISSUE_CATEGORIES:
            continue
        # Group before the cutoff, so members below it still count toward the group and never return as filler.
        group = str(rank.get("group") or observation_id)
        group_members.setdefault(group, []).append(observation_id)
        # Only a member above the cutoff can stand for the group, so the seen penalty never disqualifies it.
        if percentile < WATCH_PICK_MIN_PERCENTILE:
            continue
        score = (
            percentile
            * CATEGORY_WEIGHT[rank["category"]]
            * people_boost(row.get("watch_group_people") or 1)
            * WATCH_PICK_IMPRESSION_DECAY ** row.get("feed_impressions", 0)
        )
        if row.get("feed_viewed"):
            score -= WATCH_PICK_SEEN_PENALTY
        if group not in best_in_group or score > best_in_group[group][0]:
            best_in_group[group] = (score, row)
    grouped_ids = {member for group in best_in_group for member in group_members[group]}

    picks: list[tuple[float, Any, Any, WatchFeedEntry]] = []
    for group, (score, row) in best_in_group.items():
        rank = row["watch_rank"]
        reason = {
            "kind": "embedding_pick",
            "watch_category": rank["category"],
            "similar_count": max(len(group_members[group]), row.get("watch_group_size") or 0) - 1,
            "affected_people": row.get("watch_group_people") or 1,
        }
        picks.append(
            (
                score,
                row["created_at"],
                row.get("scanner_id"),
                WatchFeedEntry(observation_id=row["id"], reason=reason, session_id=row["session_id"]),
            )
        )
    # A pick stands for its whole feed group, so no member returns as filler.
    return finish_feed(picks, [row for row in rows if str(row["id"]) not in grouped_ids])
