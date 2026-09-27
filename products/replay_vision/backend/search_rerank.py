"""Rerank the head of an observation search with a decision model.

Embedding distance compares the query and each observation separately, so an observation that only shares the
topic ranks as high as one that shows the thing searched for. The decision model reads the query and each
observation together and answers whether the observation matches. Only the head of the list is reranked: the
model reads every question against the whole request state, so its cost grows with the square of the candidates
it sees, and splitting the head into parallel requests keeps each state small.

Search never waits on the model past `RERANK_DEADLINE_S` and never fails because of it. Any error, timeout, or
missing gateway returns the embedding order unchanged.
"""

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass

import structlog
from prometheus_client import Counter, Histogram

from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import JsonValue, NoulAnswer, NoulQuestion, SystemOneNotConfigured
from posthog.llm.system_one_client import build_system_one_client

logger = structlog.get_logger(__name__)

RERANK_MODEL = "posthog/hogference/jevk5-fp8-0.2"
RERANK_CANDIDATES = 20
RERANK_TEXT_CHARS = 500
RERANK_REQUESTS = 2
RERANK_DEADLINE_S = 2.0

_QUESTION = "Does `observations.{key}` describe a session that matches what `search` looks for?"
_CRITERIA_TRUE = "The session shows the thing the search describes actually happening."
_CRITERIA_FALSE = "The observation only shares the topic, says the thing did not happen, or describes something else."

# Shared so a search does not pay thread start-up. A timed-out request keeps its worker until the HTTP timeout
# frees it, so the pool is sized for several searches whose requests overlap.
_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="replay-vision-rerank")

_RERANK_OUTCOMES = Counter(
    "replay_vision_search_rerank_total",
    "Observation searches by rerank outcome.",
    ["outcome"],
)
_RERANK_LATENCY = Histogram(
    "replay_vision_search_rerank_latency_seconds",
    "Wall-clock time a search waited on the rerank model.",
    buckets=(0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5),
)


@dataclass(frozen=True)
class RerankCandidate:
    observation_id: str
    distance: float
    text: str


@dataclass(frozen=True)
class RerankOutcome:
    order: list[str]
    reranked: bool


def _score_chunk(query: str, chunk: Sequence[RerankCandidate], team_id: int) -> dict[str, float]:
    client = build_system_one_client(
        model=RERANK_MODEL,
        ai_product="replay_vision",
        distinct_id=team_distinct_id(team_id),
        timeout=RERANK_DEADLINE_S,
    )
    # User and observation text stays in `state`, because interpolating it into `instructions` would let it act
    # as an instruction.
    observations: dict[str, JsonValue] = {f"o{i}": c.text[:RERANK_TEXT_CHARS] for i, c in enumerate(chunk)}
    state: JsonValue = {"search": query, "observations": observations}
    questions = {
        f"q{i}": NoulQuestion(
            instructions=_QUESTION.format(key=f"o{i}"),
            criteria_true=_CRITERIA_TRUE,
            criteria_false=_CRITERIA_FALSE,
        )
        for i in range(len(chunk))
    }
    result = client.decide(state=state, questions=questions)
    scores: dict[str, float] = {}
    for i, candidate in enumerate(chunk):
        answer = result.answers[f"q{i}"]
        if not isinstance(answer, NoulAnswer):
            raise ValueError(f"expected a yes/no answer for q{i}")
        scores[candidate.observation_id] = answer.probability
    return scores


def _outcome(outcome: str, order: list[str], started: float) -> RerankOutcome:
    _RERANK_OUTCOMES.labels(outcome=outcome).inc()
    _RERANK_LATENCY.observe(time.monotonic() - started)
    return RerankOutcome(order=order, reranked=outcome == "reranked")


def rerank(query: str, candidates: Sequence[RerankCandidate], *, team_id: int) -> RerankOutcome:
    """Reorder the first `RERANK_CANDIDATES` candidates by the model's match probability, ties broken by distance.
    Candidates past the head keep their embedding order after it."""
    embedding_order = [c.observation_id for c in candidates]
    if len(candidates) < 2:
        return RerankOutcome(order=embedding_order, reranked=False)
    started = time.monotonic()
    head = list(candidates[:RERANK_CANDIDATES])
    # Interleaved chunks give each request a similar spread of close and far candidates.
    chunks = [head[i::RERANK_REQUESTS] for i in range(RERANK_REQUESTS) if head[i::RERANK_REQUESTS]]
    futures = [_EXECUTOR.submit(_score_chunk, query, chunk, team_id) for chunk in chunks]
    done, pending = wait(futures, timeout=RERANK_DEADLINE_S)
    if pending:
        for future in pending:
            future.cancel()
        logger.warning("replay_vision.search_rerank.timeout", team_id=team_id)
        return _outcome("timeout", embedding_order, started)
    scores: dict[str, float] = {}
    for future in done:
        try:
            scores.update(future.result())
        except SystemOneNotConfigured:
            return _outcome("not_configured", embedding_order, started)
        except Exception:
            logger.warning("replay_vision.search_rerank.failed", team_id=team_id, exc_info=True)
            return _outcome("error", embedding_order, started)
    distance = {c.observation_id: c.distance for c in head}
    reranked_head = sorted(scores, key=lambda observation_id: (-scores[observation_id], distance[observation_id]))
    return _outcome("reranked", reranked_head + embedding_order[len(head) :], started)
