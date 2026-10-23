"""What to watch ranking from observation embeddings.

The scan workflow ranks each observation once, from the vector it already embeds for search, so the
feed needs no model call and no sweep. Each vector is compared with fixed anchor sentences: the
closest issue anchor names the category, and its lead over the closest routine anchor is the score.
The feed turns scores into a percentile within each scanner when it loads, so a scanner that sees
errors all the time does not fill the feed.
"""

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Literal

from django.core.cache import cache

import numpy as np

from posthog.api.embedding_worker import async_generate_embedding
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.replay_vision.backend.embeddings import (
    OBSERVATION_EMBEDDING_MODEL,
    OBSERVATION_EMBEDDINGS_TABLE,
    OBSERVATION_SCOPE_PREWHERE,
    observation_scope_params,
)
from products.replay_vision.backend.watch_feed import WatchFeedEntry, finish_feed

WatchCategory = Literal["failure", "struggle", "revenue", "routine"]

# Bump when an anchor changes: scores from different anchor sets do not compare, so the feed
# ignores ranks written under another version until they age out of the window.
ANCHOR_VERSION = 1

ANCHORS: dict[WatchCategory, tuple[str, ...]] = {
    "failure": (
        "The user saw an error message and the action they tried failed.",
        "A request failed or the page crashed, showing an error to the user.",
        "The user clicked a button and nothing happened; the action silently did not work.",
        "The page got stuck loading and the user waited on a spinner that never finished.",
        "The user was blocked by a dead end, a 404 page, or an access denied message.",
    ),
    "struggle": (
        "The user repeated the same action several times because it did not give the result they expected.",
        "The user rage clicked and gave up on the task without finishing.",
        "The user hit a validation error or confusing state in a form and abandoned it.",
        "The user was stuck: they tried several different ways to do one thing and none worked.",
        "The user worked around a broken or missing feature to get their task done.",
    ),
    "revenue": (
        "The user went to billing to cancel their subscription or downgrade their plan.",
        "The user tried to upgrade or pay but the upgrade or payment failed.",
        "The user hit a usage limit that stopped a feature from working.",
        "The user contacted support frustrated about a problem.",
    ),
    "routine": (
        "The user browsed normally and completed what they came to do without any issues.",
        "A routine session with nothing notable: normal navigation and expected behavior.",
        "The user viewed a few pages and left; nothing went wrong.",
        "Nothing stands out in this session.",
        "Routine session with no errors or friction; the user did what they intended.",
        "The user browsed the pricing page and documentation normally.",
        "The user successfully completed the task without problems.",
        "The user explored different sections of the website to learn about the product.",
        "The user read through a product or documentation page.",
        "The user looked through a list and opened a few items to review them.",
        "The user started something and left before finishing, with no sign of a problem.",
        "The user never reached the part of the product this check is about.",
    ),
}
ISSUE_CATEGORIES: tuple[WatchCategory, ...] = ("failure", "struggle", "revenue")

# Struggle picks rated worth watching less often than failure and revenue picks in a blind rating.
CATEGORY_WEIGHT: dict[str, float] = {"failure": 1.0, "revenue": 1.0, "struggle": 0.85}

# Cosine distance below which two observations from one scanner describe the same thing.
DUPLICATE_MAX_DISTANCE = 0.1
DUPLICATE_LOOKBACK = timedelta(days=7)
_DUPLICATE_QUERY_TIMEOUT_S = 10

# The feed surfaces a scanner's top fifth by score, once the scanner has enough ranked rows to
# make a percentile mean something.
WATCH_PICK_MIN_PERCENTILE = 0.8
WATCH_PICK_MIN_SCANNER_ROWS = 10
WATCH_PICK_SEEN_PENALTY = 0.3

_ANCHOR_CACHE_TTL_S = 7 * 24 * 3600


@frozen
class WatchRank:
    category: WatchCategory
    contrast: float
    duplicate_of: str | None
    anchor_version: int = ANCHOR_VERSION

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _anchor_cache_key() -> str:
    return f"replay-vision:watch-rank-anchors:v{ANCHOR_VERSION}:{OBSERVATION_EMBEDDING_MODEL.value}"


def normalize(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.linalg.norm(matrix, axis=-1, keepdims=True)


# The anchors never change within a version, so each process keeps them after the first read.
_anchors_in_process: dict[str, dict[WatchCategory, np.ndarray]] = {}


async def anchor_vectors(team_id: int) -> dict[WatchCategory, np.ndarray]:
    """Unit vectors for every anchor, embedded once and cached across teams.

    Embedded under the calling team because the worker gates every call on a team's AI opt-in, and
    a team that ranks observations has already passed that gate.
    """
    key = _anchor_cache_key()
    if (in_process := _anchors_in_process.get(key)) is not None:
        return in_process
    vectors: dict[WatchCategory, list[list[float]]] | None = await cache.aget(key)
    if vectors is None:
        team = await Team.objects.aget(id=team_id)
        embedded = await asyncio.gather(
            *(
                async_generate_embedding(team, text, model=OBSERVATION_EMBEDDING_MODEL.value)
                for texts in ANCHORS.values()
                for text in texts
            )
        )
        rows = iter(response.embedding for response in embedded)
        vectors = {category: [next(rows) for _ in texts] for category, texts in ANCHORS.items()}
        await cache.aset(key, vectors, _ANCHOR_CACHE_TTL_S)
    anchors = {category: normalize(np.array(rows, dtype=float)) for category, rows in vectors.items()}
    _anchors_in_process[key] = anchors
    return anchors


def classify(vector: list[float] | np.ndarray, anchors: dict[WatchCategory, np.ndarray]) -> tuple[WatchCategory, float]:
    """The closest issue category and its lead over the closest routine anchor, given unit anchors.

    A negative lead means the observation reads more like routine than like any issue, and the
    category is then routine.
    """
    unit = normalize(np.asarray(vector, dtype=float))
    closest = {category: float(np.max(anchors[category] @ unit)) for category in anchors}
    category = max(ISSUE_CATEGORIES, key=lambda c: closest[c])
    contrast = round(closest[category] - closest["routine"], 4)
    return (category if contrast > 0 else "routine"), contrast


# Caps the vectors one duplicate lookup reads to the scanner's newest rows, so a busy scanner stays cheap.
_DUPLICATE_CANDIDATE_ROWS = 5_000


def nearest_earlier_observation(
    *, team_id: int, scanner_id: str, observation_id: str, vector: list[float], now: datetime
) -> tuple[str, float] | None:
    """The scanner's closest other observation in the lookback window, with its cosine distance."""
    with tags_context(product=Product.REPLAY_VISION, query_type="replay_vision_watch_rank_duplicate"):
        # nosemgrep: clickhouse-fstring-param-audit - table name and scope are module constants
        rows = sync_execute(
            f"""
            SELECT document_id, min(cosineDistance(embedding, %(embedding)s)) AS distance
            FROM {OBSERVATION_EMBEDDINGS_TABLE}
            PREWHERE {OBSERVATION_SCOPE_PREWHERE}
              AND timestamp >= ifNull(
                (
                    SELECT minOrNull(timestamp)
                    FROM (
                        SELECT timestamp
                        FROM {OBSERVATION_EMBEDDINGS_TABLE}
                        PREWHERE {OBSERVATION_SCOPE_PREWHERE} AND timestamp >= %(since)s
                        ORDER BY timestamp DESC
                        LIMIT %(candidate_cap)s
                    )
                ),
                %(since)s
              )
            WHERE document_id != %(observation_id)s
            GROUP BY document_id
            ORDER BY distance ASC
            LIMIT 1
            """,
            {
                **observation_scope_params(team_id, [scanner_id]),
                "embedding": vector,
                "since": now - DUPLICATE_LOOKBACK,
                "observation_id": observation_id,
                "candidate_cap": _DUPLICATE_CANDIDATE_ROWS,
            },
            team_id=team_id,
            readonly=True,
            ch_user=ClickHouseUser.REPLAY_VISION,
            settings={"max_execution_time": _DUPLICATE_QUERY_TIMEOUT_S},
        )
    if not rows:
        return None
    document_id, distance = rows[0]
    return str(document_id), float(distance)


def duplicate_root(observation_id: str, neighbour_id: str, neighbour_rank: dict[str, Any] | None) -> str | None:
    """The first observation of a duplicate group, so the group shares one id however long it grows.

    An unranked neighbour can be ranking at the same moment and pick this observation in turn, so the
    smaller id roots the pair and the two never point at each other.
    """
    if neighbour_rank is None:
        return neighbour_id if neighbour_id < observation_id else None
    root = neighbour_rank.get("duplicate_of")
    return root if isinstance(root, str) and root else neighbour_id


def current_rank(row: dict[str, Any]) -> dict[str, Any] | None:
    """The row's rank when it comes from the current anchors, else None."""
    rank = row.get("watch_rank")
    if not isinstance(rank, dict) or rank.get("anchor_version") != ANCHOR_VERSION:
        return None
    contrast = rank.get("contrast")
    if not isinstance(contrast, int | float) or isinstance(contrast, bool):
        return None
    return rank


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


def rank_watch_feed_by_embedding(rows: list[dict[str, Any]]) -> list[WatchFeedEntry]:
    """Rank candidate rows (`id`, `scanner_id`, `created_at`, `watch_rank`, `feed_viewed`) on the
    embedding rank the scan workflow wrote.

    A pick is a row in its scanner's top fifth by score whose category is an issue. Near-duplicates
    collapse to their best-scoring row, which carries the size of the group. Picks sort by weighted
    percentile, viewed rows docked, one scanner held to a share of the picks. Every other row is
    filler, trimmed to the same floor as the other rankers.
    """
    percentiles = _scanner_percentiles(rows)
    best_in_group: dict[str, tuple[float, float, dict[str, Any]]] = {}
    group_members: dict[str, list[str]] = {}
    for row in rows:
        rank = current_rank(row)
        observation_id = str(row["id"])
        percentile = percentiles.get(observation_id)
        if rank is None or percentile is None or rank.get("category") not in ISSUE_CATEGORIES:
            continue
        # Group before the cutoff, so duplicates below it still count toward the group and never return as filler.
        group = rank.get("duplicate_of") or observation_id
        group_members.setdefault(group, []).append(observation_id)
        score = percentile * CATEGORY_WEIGHT[rank["category"]]
        if row.get("feed_viewed"):
            score -= WATCH_PICK_SEEN_PENALTY
        if group not in best_in_group or score > best_in_group[group][0]:
            best_in_group[group] = (score, percentile, row)
    best_in_group = {group: best for group, best in best_in_group.items() if best[1] >= WATCH_PICK_MIN_PERCENTILE}
    grouped_ids = {member for group in best_in_group for member in group_members[group]}

    picks: list[tuple[float, Any, Any, WatchFeedEntry]] = []
    for group, (score, _, row) in best_in_group.items():
        rank = row["watch_rank"]
        reason = {
            "kind": "embedding_pick",
            "watch_category": rank["category"],
            "similar_count": len(group_members[group]) - 1,
        }
        picks.append(
            (score, row["created_at"], row.get("scanner_id"), WatchFeedEntry(observation_id=row["id"], reason=reason))
        )
    # A pick stands for its whole duplicate group, so no member returns as filler.
    return finish_feed(picks, [row for row in rows if str(row["id"]) not in grouped_ids])
