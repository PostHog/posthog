"""Jev ranking for the What to watch feed, as an alternative to the weighted score.

The multivariate `vision-watch-feed-ranker` flag selects one of two independent rankers per team:

- `weighted-score` (default): the deterministic blend in `watch_feed.py`, unchanged, no Jev calls.
- `jev-shadow`: the hourly sweep judges and caches probabilities, but the feed still ranks on the
  weighted score. This arm exists to collect probabilities and cost data before any feed changes.
- `jev`: the feed ranks on the cached probabilities alone (`rank_watch_feed_by_jev`).

Jev, the shared decision model behind the ml_inference facade, judges a whole scanner window at
once: one request carries a chunk of the scanner's recent observations as the state and one yes/no
question per observation, so each judgment is relative to the scanner's own recent sessions rather
than made in isolation. The judgments run in an hourly Temporal sweep
(`temporal/jev_watch_rank/`) and land in a Redis cache, because the feed API is synchronous over up
to 1,000 rows and must not make model calls, and the scan pipeline must not either. The two rankers
share nothing but the `WatchFeedEntry` shape, so switching the flag switches the whole ranking, not
one component of it.
"""

import json
import math
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from django.conf import settings

import structlog
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.ph_client import get_feature_flag_or_none
from posthog.redis import get_client

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest, JsonValue, NoulAnswer
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.replay_vision.backend.watch_feed import WatchFeedEntry

logger = structlog.get_logger(__name__)

WATCH_FEED_RANKER_FLAG = "vision-watch-feed-ranker"
RankerMode = Literal["weighted-score", "jev-shadow", "jev"]
JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"
JEV_INPUT_USD_PER_MILLION = 0.042
JEV_TIMEOUT_SECONDS = 3.0
# How far a viewed row drops on the 0-1 probability scale, the same intent as WATCH_SEEN_PENALTY in
# the weighted ranker: an unviewed peer with comparable evidence comes first, and a very strong seen
# row still holds its place above weak unseen rows.
JEV_SEEN_PENALTY = 0.3
# Observations per Jev request: the request carries the chunk as shared state and one question per
# observation, and a request takes at most MAX_QUESTIONS_PER_REQUEST (32) questions. A judgment is
# therefore relative to its chunk, not to the whole window at once.
WINDOW_CHUNK_SIZE = 24
_WATCH_RANK_REDIS_PREFIX = "replay-vision:jev-watch-rank:"
# Three sweep intervals: the cache survives one failed hourly sweep, and goes cold (the feed falls
# back to the recency filler tier) rather than stale when the sweep stays down.
WATCH_RANK_TTL = timedelta(hours=3)

# User text stays in the request state; these instructions refer to it by observation id only, so
# session prose cannot become an instruction (the rule from posthog/llm/system_one.py).
_WINDOW_INSTRUCTIONS = (
    "The state holds recent AI scans of recorded product sessions, all from one scanner, keyed by "
    "id. Judge the scan with id {index}: compared to the other scans in the state, should a "
    "product team spend time watching that session's recording in a 'What to watch' feed? "
    "Sessions worth watching show user friction, failures, confusion, surprising behavior, or an "
    "outcome unusual for this scanner. A routine session that reads like the rest of the state is "
    "not worth watching. A session about a product whose subject matter is errors or debugging is "
    "not automatically worth watching; only what the recorded user experienced counts."
)

_CALLS = Counter(
    "replay_vision_jev_watch_rank_calls",
    "Jev watch rank chunk requests by outcome.",
    ["outcome"],
)
_LATENCY = Histogram(
    "replay_vision_jev_watch_rank_latency_seconds",
    "Jev watch rank chunk request wall-clock latency.",
    buckets=(0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4),
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
    """Jev's judgment of one scanner's window: a probability per observation id (as a string)."""

    probabilities: dict[str, float]
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
    entry = {
        key: value
        for key, value in {
            "scanner_type": output.get("scanner_type"),
            "title": output.get("title"),
            "summary": output.get("summary"),
            "reasoning": output.get("reasoning"),
            "verdict": output.get("verdict"),
            "score": output.get("score"),
            "tags": [
                *(raw_tags if isinstance(raw_tags, list) else []),
                *(raw_freeform if isinstance(raw_freeform, list) else []),
            ],
            "notability": output.get("notability"),
            "signals_count": result.get("signals_count") if isinstance(result, dict) else None,
        }.items()
        if value not in (None, "", [])
    }
    if not any(isinstance(value := entry.get(key), str) and value.strip() for key in ("title", "summary", "reasoning")):
        return None
    return entry


def _judge_chunk(team_id: int, trace_id: str, chunk: list[tuple[str, dict[str, Any]]]) -> tuple[dict[str, float], Any]:
    state: JsonValue = {"observations": {str(index): entry for index, (_, entry) in enumerate(chunk)}}
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


def judge_scanner_window(team_id: int, scanner_id: UUID, rows: list[dict[str, Any]]) -> WindowJudgment:
    """Ask Jev which observations in one scanner's recent window are worth watching.

    `rows` carry `id` and `scanner_result` (the shape the sweep loads). Fail-soft per chunk: a
    failed chunk loses its rows' judgments and counts as failed, and the other chunks still land,
    so one bad request never empties a scanner's cache entry.
    """
    entries = [(str(row["id"]), entry) for row in rows if (entry := _window_entry(row)) is not None]
    chunks = [entries[start : start + WINDOW_CHUNK_SIZE] for start in range(0, len(entries), WINDOW_CHUNK_SIZE)]
    probabilities: dict[str, float] = {}
    model: str | None = None
    failed_chunks = 0
    input_tokens = 0
    estimated_cost = 0.0
    for chunk in chunks:
        started = perf_counter()
        try:
            chunk_probabilities, result = _judge_chunk(team_id, f"{scanner_id}", chunk)
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
        model=model,
        chunks=len(chunks),
        failed_chunks=failed_chunks,
        input_tokens=input_tokens,
        estimated_cost_usd=estimated_cost,
    )


def _watch_rank_key(team_id: int, scanner_id: UUID | str) -> str:
    return f"{_WATCH_RANK_REDIS_PREFIX}{team_id}:{scanner_id}"


def store_watch_ranks(team_id: int, scanner_id: UUID, judgment: WindowJudgment) -> None:
    get_client(settings.REPLAY_VISION_REDIS_URL).setex(
        _watch_rank_key(team_id, scanner_id),
        WATCH_RANK_TTL,
        json.dumps(
            {
                "model": judgment.model,
                "judged_at": datetime.now(UTC).isoformat(),
                "probabilities": judgment.probabilities,
            }
        ),
    )


def load_watch_ranks(team_id: int, scanner_ids: list[UUID]) -> dict[str, float]:
    """The cached probabilities for these scanners, keyed by observation id. Any malformed or
    missing cache entry contributes nothing, so a cold cache degrades the Jev feed to the recency
    filler tier rather than failing the request."""
    if not scanner_ids:
        return {}
    probabilities: dict[str, float] = {}
    try:
        values = get_client(settings.REPLAY_VISION_REDIS_URL).mget(
            [_watch_rank_key(team_id, scanner_id) for scanner_id in scanner_ids]
        )
        for value in values:
            if not value:
                continue
            stored = json.loads(value).get("probabilities")
            if not isinstance(stored, dict):
                continue
            for observation_id, probability in stored.items():
                # Clamped like the weighted ranker clamps notability, because a cache can carry
                # anything (and bool is an int subclass).
                if isinstance(probability, int | float) and not isinstance(probability, bool):
                    probabilities[str(observation_id)] = min(1.0, max(0.0, float(probability)))
    except Exception:
        logger.exception("Jev watch rank cache read failed", team_id=team_id)
    return probabilities


def rank_watch_feed_by_jev(rows: list[dict[str, Any]], probabilities: dict[str, float]) -> list[WatchFeedEntry]:
    """Rank candidate rows (`id`, `created_at`, `feed_viewed`) on Jev's cached watchability alone:
    highest probability first, viewed rows docked, newest as the tiebreak.

    Independent of `rank_watch_feed_candidates` on purpose: the flag picks a whole ranker, so this
    arm measures Jev's judgment without any component of the weighted score mixed in. A row without
    a cached probability (not yet swept, or the cache went cold) sorts below every judged row by
    recency and carries the same filler reasons the weighted ranker uses for no-evidence rows.
    """
    judged: list[tuple[float, Any, WatchFeedEntry]] = []
    unjudged: list[tuple[bool, Any, WatchFeedEntry]] = []
    for row in rows:
        probability = probabilities.get(str(row["id"]))
        viewed = bool(row.get("feed_viewed"))
        if probability is not None:
            entry = WatchFeedEntry(
                observation_id=row["id"], reason={"kind": "jev_watchable", "jev_probability": probability}
            )
            judged.append((probability - (JEV_SEEN_PENALTY if viewed else 0.0), row["created_at"], entry))
        else:
            entry = WatchFeedEntry(observation_id=row["id"], reason={"kind": "recent" if viewed else "unviewed_recent"})
            unjudged.append((not viewed, row["created_at"], entry))
    judged.sort(key=lambda item: (item[0], item[1]), reverse=True)
    unjudged.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for *_, entry in judged] + [entry for *_, entry in unjudged]
