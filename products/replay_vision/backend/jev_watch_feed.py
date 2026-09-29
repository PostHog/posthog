"""Jev ranking for the What to watch feed, as an alternative to the weighted score.

The multivariate `vision-watch-feed-ranker` flag selects one of two independent rankers per team:

- `weighted-score` (default): the deterministic blend in `watch_feed.py`, unchanged, no Jev calls.
- `jev-shadow`: the hourly sweep judges and caches probabilities, but the feed still ranks on the
  weighted score. This arm exists to collect probabilities and cost data before any feed changes.
- `jev`: the feed ranks on the cached probabilities alone (`rank_watch_feed_by_jev`).

Jev, the shared decision model behind the ml_inference facade, judges each observation once, in
company: one request carries a chunk of observations as the state and one yes/no question per
observation, with already-judged rows padding a short chunk as context, so every judgment sees the
scanner's own recent sessions rather than standing alone. The hourly Temporal sweep
(`temporal/jev_watch_rank/`) judges only the rows without a cached probability and merges the
results into a Redis cache, so coverage accumulates across sweeps at a bounded hourly cost whatever
the scanner's volume. The cache exists because the feed API is synchronous over up to 1,000 rows
and must not make model calls, and the scan pipeline must not either. The two rankers share nothing
but the `WatchFeedEntry` shape, so switching the flag switches the whole ranking, not one component
of it.
"""

import json
import math
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

from django.conf import settings

import structlog
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.ph_client import get_feature_flag_or_none
from posthog.redis import get_client

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import (
    MAX_QUESTIONS_PER_REQUEST,
    DecisionQuestion,
    DecisionRequest,
    JsonValue,
    NoulAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.replay_vision.backend.watch_feed import WatchFeedEntry

logger = structlog.get_logger(__name__)

WATCH_FEED_RANKER_FLAG = "vision-watch-feed-ranker"
RankerMode = Literal["weighted-score", "jev-shadow", "jev"]
# The JevK5 build PostHog hosts on the AI gateway, which is the only backend the ml_inference
# facade reaches. The vendor (typesafe.ai) is not approved for customer data, and observation prose
# is customer data, so never point this at a vendor model id.
JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"
JEV_INPUT_USD_PER_MILLION = 0.042
# A chunk request carries up to WINDOW_CHUNK_SIZE questions over a multi-observation state, so it
# runs far longer than the single-question decisions Signals times out at 3s. Matches the gateway
# client's own default; the sweep is background work, so latency is cheap and a timeout loses a
# whole chunk's judgments.
JEV_TIMEOUT_SECONDS = 30.0
# How far a viewed row drops on the 0-1 probability scale, the same intent as WATCH_SEEN_PENALTY in
# the weighted ranker: an unviewed peer with comparable evidence comes first, and a very strong seen
# row still holds its place above weak unseen rows.
JEV_SEEN_PENALTY = 0.3
# Below this probability a judged row carries no evidence: it falls to the same recency filler tier
# as an unjudged row, so its card never claims the model judged it worth watching, and a judged-low
# row cannot outrank a fresh observation the sweep has not seen yet. Tier membership uses the raw
# probability; the seen penalty only orders rows inside the evidence tier.
JEV_WATCHABLE_MIN = 0.5
# One incident can put many near-identical watchable sessions on one scanner, and a pure probability
# sort would fill the top of the feed with them. Hold each scanner to this share of the evidence
# tier as it is placed (same intent as WATCH_FEED_MAX_SIGNAL_SHARE in the weighted ranker), with a
# floor so a short feed is not over-constrained; the overflow trails the tier instead of leaving it.
JEV_MAX_SCANNER_SHARE = 0.4
_SCANNER_SPREAD_FLOOR = 3
# Observations per Jev request: the request carries the chunk as shared state and one question per
# observation, so the facade's per-request question cap is the most context one judgment can get. A
# judgment is therefore relative to its chunk, not to the whole window at once.
WINDOW_CHUNK_SIZE = MAX_QUESTIONS_PER_REQUEST
# Per-entry prose caps, so a 24-entry chunk state stays small and per-chunk latency predictable
# whatever the scanner's configured summary length.
_MAX_TITLE_CHARS = 300
_MAX_PROSE_CHARS = 1500
_MAX_TAGS = 20
_WATCH_RANK_REDIS_PREFIX = "replay-vision:jev-watch-rank:"
# Judgments are append-only per observation and the sweep prunes entries that leave the window, so
# a long lifetime is resilience, not staleness: the cache survives a day of failed sweeps before
# the feed falls back to the recency filler tier and coverage rebuilds at the judging cap per hour.
WATCH_RANK_TTL = timedelta(hours=25)

# User text stays in the request state; these instructions refer to it by observation id only, so
# session prose cannot become an instruction (the rule from posthog/llm/system_one.py). Each
# question is an independent probability, not a pick, and the instruction says so: without the
# "every answer may be no" sentence a relative phrasing grades the window on a curve, forcing
# winners out of an all-routine window and suppressing an all-failures one.
_WINDOW_INSTRUCTIONS = (
    "The state holds recent AI scans of recorded product sessions, all from one scanner, keyed by "
    "id. Judge the scan with id {index} on its own evidence: should a product team spend time "
    "watching that session's recording in a 'What to watch' feed? "
    "Sessions worth watching show user friction, failures, confusion, surprising behavior, or an "
    "outcome unusual for this scanner. "
    "Use the other scans in the state only as context for what is routine for this scanner; the "
    "scans do not compete with each other. It is correct to answer no for every scan in the state "
    "when nothing stands out, and to answer yes for many scans when many sessions show real "
    "problems. "
    "A session about a product whose subject matter is errors or debugging is not automatically "
    "worth watching; only what the recorded user experienced counts."
)

_CALLS = Counter(
    "replay_vision_jev_watch_rank_calls",
    "Jev watch rank chunk requests by outcome.",
    ["outcome"],
)
_LATENCY = Histogram(
    "replay_vision_jev_watch_rank_latency_seconds",
    "Jev watch rank chunk request wall-clock latency.",
    buckets=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
)
_INPUT_TOKENS = Counter(
    "replay_vision_jev_watch_rank_input_tokens",
    "Jev input tokens reported by the decision gateway.",
)
_ESTIMATED_COST = Counter(
    "replay_vision_jev_watch_rank_estimated_cost_usd",
    "Jev input-token cost at the gateway catalog price.",
)


def watch_feed_ranker(team_id: int) -> RankerMode:
    """The team's arm of the watch feed ranker experiment. Any flag failure reads as the default
    arm, so the sweep and the feed never fail on flag evaluation."""
    value = get_feature_flag_or_none(
        WATCH_FEED_RANKER_FLAG,
        f"team-{team_id}",
        groups={"project": str(team_id)},
        group_properties={"project": {"id": team_id}},
        send_feature_flag_events=False,
    )
    if value == "jev-shadow":
        return "jev-shadow"
    if value == "jev":
        return "jev"
    return "weighted-score"


@frozen
class WindowJudgment:
    """Jev's judgment of one batch of observations: a probability per observation id (as a string)."""

    probabilities: dict[str, float]
    # Rows with no prose to judge. The sweep records these as judged, so they settle into the
    # filler tier once instead of being refetched every sweep; a failed chunk's rows are absent
    # from both fields and retry next sweep.
    skipped_no_prose: tuple[str, ...]
    model: str | None
    chunks: int
    failed_chunks: int
    input_tokens: int
    estimated_cost_usd: float


def _window_entry(row: dict[str, Any]) -> dict[str, Any] | None:
    """The judgeable view of one observation row, or None when the row carries no prose to judge."""
    result = row.get("scanner_result")
    output = result.get("model_output") if isinstance(result, dict) else None
    if not isinstance(output, dict):
        return None
    raw_tags = output.get("tags")
    raw_freeform = output.get("tags_freeform")

    def clipped(value: Any, limit: int) -> Any:
        return value[:limit] if isinstance(value, str) else value

    entry = {
        key: value
        for key, value in {
            "scanner_type": output.get("scanner_type"),
            "title": clipped(output.get("title"), _MAX_TITLE_CHARS),
            "summary": clipped(output.get("summary"), _MAX_PROSE_CHARS),
            "reasoning": clipped(output.get("reasoning"), _MAX_PROSE_CHARS),
            "verdict": output.get("verdict"),
            "score": output.get("score"),
            "tags": [
                *(raw_tags if isinstance(raw_tags, list) else []),
                *(raw_freeform if isinstance(raw_freeform, list) else []),
            ][:_MAX_TAGS],
            "notability": output.get("notability"),
            "signals_count": result.get("signals_count") if isinstance(result, dict) else None,
        }.items()
        if value not in (None, "", [])
    }
    if not any(isinstance(value := entry.get(key), str) and value.strip() for key in ("title", "summary", "reasoning")):
        return None
    return entry


def _judge_chunk(
    team_id: int,
    trace_id: str,
    chunk: list[tuple[str, dict[str, Any]]],
    context: list[dict[str, Any]],
) -> tuple[dict[str, float], Any]:
    """One request: questions about `chunk`, with `context` entries in the state as extra siblings.
    Context pads a small chunk (a quiet hour adds only a few new rows) so its judgments still see
    what routine looks like for this scanner."""
    entries = [entry for _, entry in chunk] + context
    state: JsonValue = {"observations": {str(index): entry for index, entry in enumerate(entries)}}
    questions = {
        f"watch_{index}": DecisionQuestion(
            type=DecisionQuestionType.NOUL, instructions=_WINDOW_INSTRUCTIONS.format(index=index)
        )
        for index in range(len(chunk))
    }
    result = decision_api.decide_when_available(
        DecisionRequest(
            team_id=team_id,
            state=state,
            questions=questions,
            model=JEV_MODEL,
            ai_product="replay_vision",
            trace_id=trace_id,
        ),
        timeout_seconds=JEV_TIMEOUT_SECONDS,
    )
    probabilities: dict[str, float] = {}
    for index, (observation_id, _) in enumerate(chunk):
        answer = result.answers.get(f"watch_{index}")
        if (
            not isinstance(answer, NoulAnswer)
            or not math.isfinite(answer.probability)
            or not 0 <= answer.probability <= 1
        ):
            raise ValueError("Jev returned an invalid watchability probability")
        probabilities[observation_id] = answer.probability
    return probabilities, result


def judge_scanner_window(
    team_id: int, scanner_id: UUID, rows: list[dict[str, Any]], context_rows: list[dict[str, Any]] | None = None
) -> WindowJudgment:
    """Ask Jev which of these observations are worth watching, one probability per row.

    `rows` and `context_rows` carry `id` and `scanner_result` (the shape the sweep loads). Context
    rows enter the request state without questions, so a small batch of new rows is still judged
    against the scanner's routine. Fail-soft per chunk: a failed chunk loses its rows' judgments
    and counts as failed, and the other chunks still land, so one bad request never empties a
    scanner's cache entry.
    """
    entries = [(str(row["id"]), entry) for row in rows if (entry := _window_entry(row)) is not None]
    entry_ids = {entry_id for entry_id, _ in entries}
    skipped_no_prose = tuple(str(row["id"]) for row in rows if str(row["id"]) not in entry_ids)
    context = [entry for row in context_rows or [] if (entry := _window_entry(row)) is not None]
    chunks = [entries[start : start + WINDOW_CHUNK_SIZE] for start in range(0, len(entries), WINDOW_CHUNK_SIZE)]
    # One trace per window run, so a window's chunks group in AI observability without merging runs.
    trace_id = str(uuid4())
    probabilities: dict[str, float] = {}
    model: str | None = None
    failed_chunks = 0
    input_tokens = 0
    estimated_cost = 0.0
    for chunk in chunks:
        started = perf_counter()
        try:
            # The state holds at most WINDOW_CHUNK_SIZE entries, so context only pads short chunks.
            chunk_probabilities, result = _judge_chunk(
                team_id, trace_id, chunk, context[: WINDOW_CHUNK_SIZE - len(chunk)]
            )
        except Exception as error:
            _LATENCY.observe(perf_counter() - started)
            _CALLS.labels(type(error).__name__).inc()
            failed_chunks += 1
            # The gateway error body can echo the state, which holds recording-derived prose, so
            # only the error type leaves here.
            logger.warning(
                "Jev watch rank chunk failed",
                team_id=team_id,
                scanner_id=str(scanner_id),
                error_type=type(error).__name__,
            )
            continue
        _LATENCY.observe(perf_counter() - started)
        _CALLS.labels("ok").inc()
        probabilities.update(chunk_probabilities)
        model = result.model
        input_tokens += result.input_tokens
        chunk_cost = result.input_tokens * JEV_INPUT_USD_PER_MILLION / 1_000_000
        estimated_cost += chunk_cost
        _INPUT_TOKENS.inc(result.input_tokens)
        _ESTIMATED_COST.inc(chunk_cost)
    return WindowJudgment(
        probabilities=probabilities,
        skipped_no_prose=skipped_no_prose,
        model=model,
        chunks=len(chunks),
        failed_chunks=failed_chunks,
        input_tokens=input_tokens,
        estimated_cost_usd=estimated_cost,
    )


# The watchable map (probability >= JEV_WATCHABLE_MIN, all the feed reads) lives apart from the
# judged-id set (everything the sweep has bought, read only by the sweep's skip logic): the feed
# loads every readable scanner's key on each request, so its keys must stay small however large a
# scanner's judged window grows.
def _watchable_key(team_id: int, scanner_id: UUID | str) -> str:
    return f"{_WATCH_RANK_REDIS_PREFIX}watchable:{team_id}:{scanner_id}"


def _judged_key(team_id: int, scanner_id: UUID | str) -> str:
    return f"{_WATCH_RANK_REDIS_PREFIX}judged:{team_id}:{scanner_id}"


def refresh_watch_ranks_ttl(team_id: int, scanner_id: UUID) -> None:
    client = get_client(settings.REPLAY_VISION_REDIS_URL)
    client.expire(_watchable_key(team_id, scanner_id), WATCH_RANK_TTL)
    client.expire(_judged_key(team_id, scanner_id), WATCH_RANK_TTL)


def store_watch_ranks(
    team_id: int, scanner_id: UUID, judged_ids: Collection[str], watchable: dict[str, float], model: str | None
) -> None:
    client = get_client(settings.REPLAY_VISION_REDIS_URL)
    client.setex(_judged_key(team_id, scanner_id), WATCH_RANK_TTL, json.dumps({"ids": sorted(judged_ids)}))
    client.setex(
        _watchable_key(team_id, scanner_id),
        WATCH_RANK_TTL,
        json.dumps(
            {
                "model": model,
                "judged_at": datetime.now(UTC).isoformat(),
                "probabilities": watchable,
            }
        ),
    )


def load_judged_ids(team_id: int, scanner_id: UUID) -> set[str]:
    """Every observation id the sweep has judged for this scanner. A missing key is an empty set.

    A Redis read failure raises: an unreadable cache must not read as an empty one, or the sweep
    re-buys the scanner's judgments and its next write replaces entries it never saw. A stored
    value that cannot be parsed reads as empty instead, because rewriting it loses nothing.
    """
    value = get_client(settings.REPLAY_VISION_REDIS_URL).get(_judged_key(team_id, scanner_id))
    if not value:
        return set()
    try:
        stored = json.loads(value).get("ids")
    except Exception:
        logger.exception("Jev watch rank judged-set malformed", team_id=team_id)
        return set()
    return {str(judged_id) for judged_id in stored} if isinstance(stored, list) else set()


def _parse_watchable(value: Any) -> dict[str, float]:
    if not value:
        return {}
    try:
        stored = json.loads(value).get("probabilities")
    except Exception:
        logger.exception("Jev watch rank cache value malformed")
        return {}
    if not isinstance(stored, dict):
        return {}
    probabilities: dict[str, float] = {}
    for observation_id, probability in stored.items():
        # Clamped like the weighted ranker clamps notability, because a cache can carry anything
        # (and bool is an int subclass).
        if isinstance(probability, int | float) and not isinstance(probability, bool):
            probabilities[str(observation_id)] = min(1.0, max(0.0, float(probability)))
    return probabilities


def load_scanner_watch_ranks(team_id: int, scanner_id: UUID) -> dict[str, float]:
    """The sweep's read of one scanner's watchable map. Raises on a Redis read failure, because the
    sweep merges what it loads back into the store, so writing over a map it never saw drops
    entries. The feed reads through `load_watch_ranks`, which fails soft instead."""
    return _parse_watchable(get_client(settings.REPLAY_VISION_REDIS_URL).get(_watchable_key(team_id, scanner_id)))


def load_watch_ranks(team_id: int, scanner_ids: list[UUID]) -> dict[str, float]:
    """The cached watchable probabilities for these scanners, keyed by observation id. Fail-soft:
    any malformed, missing, or unreachable cache entry contributes nothing, so the Jev feed degrades
    to the recency filler tier rather than failing the request."""
    if not scanner_ids:
        return {}
    probabilities: dict[str, float] = {}
    try:
        values = get_client(settings.REPLAY_VISION_REDIS_URL).mget(
            [_watchable_key(team_id, scanner_id) for scanner_id in scanner_ids]
        )
        for value in values:
            probabilities |= _parse_watchable(value)
    except Exception:
        logger.exception("Jev watch rank cache read failed", team_id=team_id)
    return probabilities


def _scan_notability_reason(row: dict[str, Any]) -> str | None:
    result = row.get("scanner_result")
    output = result.get("model_output") if isinstance(result, dict) else None
    reason = output.get("notability_reason") if isinstance(output, dict) else None
    return reason if isinstance(reason, str) and reason.strip() else None


def _spread_scanners(ordered: list[tuple[Any, WatchFeedEntry]]) -> list[WatchFeedEntry]:
    """Hold each scanner to JEV_MAX_SCANNER_SHARE of the evidence tier as it is placed.

    Checked per place rather than over the whole list because the view slices the head: a feed of 5
    obeys the same share as a feed of 50. Overflow trails the tier in probability order — reordering
    for breadth is the job here, shortening the feed is not.
    """
    placed: list[WatchFeedEntry] = []
    deferred: list[WatchFeedEntry] = []
    counts: dict[Any, int] = {}
    for scanner_id, entry in ordered:
        allowed = max(_SCANNER_SPREAD_FLOOR, math.ceil(JEV_MAX_SCANNER_SHARE * (len(placed) + 1)))
        if counts.get(scanner_id, 0) >= allowed:
            deferred.append(entry)
        else:
            counts[scanner_id] = counts.get(scanner_id, 0) + 1
            placed.append(entry)
    return placed + deferred


def rank_watch_feed_by_jev(rows: list[dict[str, Any]], probabilities: dict[str, float]) -> list[WatchFeedEntry]:
    """Rank candidate rows (`id`, `scanner_id`, `created_at`, `scanner_result`, `feed_viewed`) on
    Jev's cached watchability alone: highest probability first, one scanner held to a share of the
    tier, viewed rows docked, newest as the tiebreak.

    Independent of `rank_watch_feed_candidates` on purpose: the flag picks a whole ranker, so this
    arm measures Jev's judgment without any component of the weighted score mixed in. Rows without
    evidence sort below every watchable row by recency, with the same filler reasons the weighted
    ranker uses: rows the model rated below `JEV_WATCHABLE_MIN`, rows without a cached probability
    (not yet swept, or the cache went cold), and rows outside the sweep's window.
    """
    watchable: list[tuple[float, Any, Any, WatchFeedEntry]] = []
    filler: list[tuple[bool, Any, WatchFeedEntry]] = []
    for row in rows:
        probability = probabilities.get(str(row["id"]))
        viewed = bool(row.get("feed_viewed"))
        if probability is not None and probability >= JEV_WATCHABLE_MIN:
            reason: dict[str, Any] = {"kind": "jev_watchable", "jev_probability": probability}
            # The scan's own sentence, so the card says why the session is worth watching instead
            # of only that the model said so; the frontend prefers it over kind-derived copy.
            if notability_reason := _scan_notability_reason(row):
                reason["notability_reason"] = notability_reason
            entry = WatchFeedEntry(observation_id=row["id"], reason=reason)
            watchable.append(
                (probability - (JEV_SEEN_PENALTY if viewed else 0.0), row["created_at"], row.get("scanner_id"), entry)
            )
        else:
            entry = WatchFeedEntry(observation_id=row["id"], reason={"kind": "recent" if viewed else "unviewed_recent"})
            filler.append((not viewed, row["created_at"], entry))
    watchable.sort(key=lambda item: (item[0], item[1]), reverse=True)
    filler.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return _spread_scanners([(scanner_id, entry) for _, _, scanner_id, entry in watchable]) + [
        entry for *_, entry in filler
    ]
