"""Judge a sample of auto-merge decisions for the metrics event. Nothing here can change a merge."""

import time
import threading
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
)

import structlog
import temporalio.exceptions
from anthropic import Anthropic

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_ai_gateway_anthropic_client, team_distinct_id
from posthog.models import Team
from posthog.temporal.common.shutdown import WorkerShuttingDownError
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.fingerprint_embedding_result.judge import (
    DEFAULT_AUTO_MERGE_CONFIG,
    AutoMergeConfig,
    _truncate,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    CLOSEST_FINGERPRINTS_WINDOW,
    AutoMergeOutcome,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
    parse_embedding_timestamp,
)
from products.error_tracking.backend.temporal.grouping_judge.algorithms import LIVE_ALGORITHM, decisions_for
from products.error_tracking.backend.temporal.grouping_judge.config import current_judge_config
from products.error_tracking.backend.temporal.grouping_judge.judge import JUDGE_MODEL, JudgeVerdict, judge_pair
from products.error_tracking.backend.temporal.grouping_judge.sampling import (
    JudgeSample,
    band_for,
    distance_bucket_for,
    sample_pair,
)
from products.error_tracking.backend.temporal.grouping_judge.types import JudgeOutcome, LiveDecision

logger = structlog.get_logger(__name__)

AI_PRODUCT = "error_tracking_grouping_judge"
# Bounds the ClickHouse text fetch and every judge call. A sampled issue's alert waits at most this long for them.
TOTAL_BUDGET_SECONDS = 10.0
TEXT_QUERY_MAX_EXECUTION_SECONDS = 3
# A re-judge with less time than this left would most likely time out, so it is skipped.
MIN_REJUDGE_SECONDS = 2.0

_DOCUMENT_TEXT_QUERY_TEMPLATE = """
    SELECT document_id, argMax(content, inserted_at)
    FROM {table}
    WHERE product = 'error_tracking'
    AND document_type = 'fingerprint'
    AND rendering = {{rendering}}
    AND team_id = {{team_id}}
    AND timestamp >= {{min_timestamp}}
    AND document_id IN ({{document_a}}, {{document_b}})
    GROUP BY document_id
    """
# Reads the same model-specific table as the closest-fingerprints query, so both texts are in it.
DOCUMENT_TEXT_QUERY_BY_MODEL = {
    model_name: _DOCUMENT_TEXT_QUERY_TEMPLATE.format(table=table)
    for model_name, table in (
        ("text-embedding-3-large-3072", "document_embeddings_text_embedding_3_large_3072"),
        ("text-embedding-3-small-1536", "document_embeddings_text_embedding_3_small_1536"),
    )
}

# The judge runs on its own thread so the activity can stop waiting at the budget even when a
# call ignores its own timeout. A timed-out call keeps its thread until its own timeouts end it.
# The ClickHouse socket has no client timeout, so a sample that finds every thread busy skips the
# judge instead of queueing behind threads that may never come back.
_MAX_WORKERS = 4
_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="error-tracking-grouping-judge")
_free_workers = threading.BoundedSemaphore(_MAX_WORKERS)


@frozen
class _JudgeResult:
    outcome: JudgeOutcome
    same_issue: bool | None = None
    rejudge_same_issue: bool | None = None


def _is_cancellation(error: BaseException) -> bool:
    return temporalio.exceptions.is_cancelled_exception(error) or isinstance(error, WorkerShuttingDownError)


def _live_decision(merge_outcome: AutoMergeOutcome | None) -> LiveDecision:
    if merge_outcome is None:
        return "error"
    return "merge" if merge_outcome.merged_count > 0 else "no_merge"


def _fetch_document_texts(
    team: Team, inputs: FingerprintEmbeddingResultInputs, neighbour_fingerprint: str
) -> dict[str, str]:
    query_text = DOCUMENT_TEXT_QUERY_BY_MODEL.get(inputs.model_name)
    if query_text is None:
        raise ValueError(f"No document text query for embedding model: {inputs.model_name}")
    # The closest-fingerprints window, so the neighbour's row is inside it.
    min_timestamp = parse_embedding_timestamp(inputs.timestamp) - CLOSEST_FINGERPRINTS_WINDOW
    query = parse_select(
        query_text,
        placeholders={
            "rendering": ast.Constant(value=inputs.rendering),
            "team_id": ast.Constant(value=team.id),
            "min_timestamp": ast.Constant(value=min_timestamp),
            "document_a": ast.Constant(value=inputs.fingerprint),
            "document_b": ast.Constant(value=neighbour_fingerprint),
        },
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ErrorTrackingGroupingJudgeDocumentTexts",
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
        settings=HogQLGlobalSettings(max_execution_time=TEXT_QUERY_MAX_EXECUTION_SECONDS),
    )
    return {row[0]: row[1] for row in response.results if row[1]}


def _judge_once(
    client: Anthropic, *, new_text: str, neighbour_text: str, swapped: bool, deadline: float
) -> JudgeVerdict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return JudgeVerdict(outcome="timeout")
    first, second = (neighbour_text, new_text) if swapped else (new_text, neighbour_text)
    return judge_pair(client, document_a=first, document_b=second, timeout_seconds=remaining)


@close_db_connections
def _judge_in_worker(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    neighbour_fingerprint: str,
    sample: JudgeSample,
    deadline: float,
) -> _JudgeResult:
    # A task that waited in the queue past the deadline has no caller left to read its result.
    if time.monotonic() >= deadline:
        return _JudgeResult(outcome="timeout")
    texts = _fetch_document_texts(team, inputs, neighbour_fingerprint)
    # A workflow started before the activity input carried the text has to read it from ClickHouse.
    new_text = inputs.content or texts.get(inputs.fingerprint)
    neighbour_text = texts.get(neighbour_fingerprint)
    if new_text is None or neighbour_text is None:
        return _JudgeResult(outcome="no_text")
    # Keeps the message and the throw site, which the renderer puts at the end of a long stack.
    new_text, neighbour_text = _truncate(new_text), _truncate(neighbour_text)

    try:
        client = build_ai_gateway_anthropic_client(
            ai_product=AI_PRODUCT, team_id=team.id, distinct_id=team_distinct_id(team.id)
        )
    except ValueError:
        return _JudgeResult(outcome="unavailable")
    with client:
        verdict = _judge_once(
            client, new_text=new_text, neighbour_text=neighbour_text, swapped=sample.swapped, deadline=deadline
        )
        if verdict.outcome != "judged" or not sample.rejudge or deadline - time.monotonic() < MIN_REJUDGE_SECONDS:
            return _JudgeResult(outcome=verdict.outcome, same_issue=verdict.same_issue)
        rejudge = _judge_once(
            client, new_text=new_text, neighbour_text=neighbour_text, swapped=not sample.swapped, deadline=deadline
        )
    return _JudgeResult(outcome=verdict.outcome, same_issue=verdict.same_issue, rejudge_same_issue=rejudge.same_issue)


def _judge(
    team: Team, inputs: FingerprintEmbeddingResultInputs, neighbour_fingerprint: str, sample: JudgeSample
) -> _JudgeResult:
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    try:
        # A null approval counts as not approved.
        if team.organization.is_ai_data_processing_approved is not True:
            return _JudgeResult(outcome="no_consent")
        if not _free_workers.acquire(blocking=False):
            return _JudgeResult(outcome="unavailable")
        try:
            future = _executor.submit(_judge_in_worker, team, inputs, neighbour_fingerprint, sample, deadline)
        except BaseException:
            _free_workers.release()
            raise
        future.add_done_callback(lambda _: _free_workers.release())
        return future.result(timeout=max(deadline - time.monotonic(), 0))
    except FuturesTimeoutError:
        return _JudgeResult(outcome="timeout")
    except Exception as error:
        if _is_cancellation(error):
            # A worker drain raises into this thread while it waits. The merge has committed, and a
            # retry cannot recover its reopened target, so the activity must still return its result.
            return _JudgeResult(outcome="cancelled")
        # Caught here rather than only at the entry point, so the row keeps its other judge properties.
        logger.exception("error_tracking.grouping_judge.failed", team_id=team.id)
        return _JudgeResult(outcome="unavailable")


def _grouping_judge_properties(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    closest_fingerprints: list[SimilarFingerprintDistance],
    merge_outcome: AutoMergeOutcome | None,
    merge_config: AutoMergeConfig,
) -> dict[str, object]:
    properties: dict[str, object] = {
        "live_decision": _live_decision(merge_outcome),
        "live_target_fingerprint": merge_outcome.target_fingerprint if merge_outcome is not None else None,
        "live_merge_decision": merge_outcome.merge_decision if merge_outcome is not None else None,
        # The fixed rule describes the merge only while the flag leaves every setting at its default.
        "live_algorithm": LIVE_ALGORITHM.id if merge_config == DEFAULT_AUTO_MERGE_CONFIG else "auto_merge_config",
        "live_auto_merge_threshold": merge_config.auto_merge_threshold,
        "live_judge_enabled": merge_config.judge_enabled,
        "live_judge_shadow": merge_config.judge_shadow,
        "live_judge_cutoff": merge_config.judge_cutoff,
        "live_judge_max_distance": merge_config.judge_max_distance,
        "decisions": {},
        "judge_band": None,
        "distance_bucket": None,
        "judge_sampled": False,
    }
    if not closest_fingerprints:
        return properties
    nearest = closest_fingerprints[0]
    band = band_for(nearest.distance)
    properties.update(
        decisions=decisions_for(nearest.distance),
        judge_band=band,
        distance_bucket=distance_bucket_for(nearest.distance),
    )
    # A failed merge is retried, and the retry judges the pair, so judging it here would pay twice.
    if merge_outcome is None:
        return properties
    config = current_judge_config()
    if not config.is_enabled_for(team.id):
        return properties
    sample = sample_pair(team.id, inputs.fingerprint, config.sample_rate)
    if not sample.sampled:
        return properties

    # Judge the pair the merge used, which is not rank 1 when the merge skipped it.
    judged_fingerprint = merge_outcome.target_fingerprint or nearest.fingerprint
    start = time.monotonic()
    result = _judge(team, inputs, judged_fingerprint, sample)
    # Document text and the model's reasoning hold customer data, so neither goes in the event.
    return {
        **properties,
        "judge_sampled": True,
        "judge_target_fingerprint": judged_fingerprint,
        "judge_outcome": result.outcome,
        "judge_same_issue": result.same_issue,
        "judge_swapped": sample.swapped,
        "judge_rejudge_same_issue": result.rejudge_same_issue,
        "judge_model": JUDGE_MODEL,
        "judge_view": inputs.rendering,
        "judge_duration_ms": (time.monotonic() - start) * 1000,
    }


def grouping_judge_properties(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    closest_fingerprints: list[SimilarFingerprintDistance],
    merge_outcome: AutoMergeOutcome | None,
    merge_config: AutoMergeConfig = DEFAULT_AUTO_MERGE_CONFIG,
) -> dict[str, object]:
    """Decision and judge properties for the metrics event. `merge_outcome` is None when the merge raised.

    Never raises, and returns within about `TOTAL_BUDGET_SECONDS`.
    """
    try:
        return _grouping_judge_properties(team, inputs, closest_fingerprints, merge_outcome, merge_config)
    except Exception:
        logger.exception("error_tracking.grouping_judge.properties_failed", team_id=team.id)
        return {"live_decision": _live_decision(merge_outcome)}
