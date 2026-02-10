import pytest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from asgiref.sync import sync_to_async
from autoevals.partial import ScorerWithPartial
from braintrust import EvalCase, Score, wrap_openai
from openai import AsyncOpenAI

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.eval.conftest import EMBEDDING_DIMENSIONS, OPENAI_EMBEDDING_MODEL
from products.signals.backend.eval.dataset import EVAL_CASES
from products.signals.backend.temporal.llm import generate_search_queries, match_signal_with_llm
from products.signals.backend.temporal.types import ExistingReportMatch, SignalCandidate

from ee.hogai.eval.base import MaxPublicEval

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536

CANDIDATE_SEARCH_QUERY = """
    SELECT
        document_id,
        content,
        JSONExtractString(metadata, 'report_id') as report_id,
        JSONExtractString(metadata, 'source_product') as source_product,
        JSONExtractString(metadata, 'source_type') as source_type,
        cosineDistance(embedding, {embedding}) as distance
    FROM (
        SELECT
            document_id,
            argMax(content, inserted_at) as content,
            argMax(metadata, inserted_at) as metadata,
            argMax(embedding, inserted_at) as embedding,
            argMax(timestamp, inserted_at) as timestamp
        FROM document_embeddings
        WHERE model_name = {model_name}
          AND product = 'signals'
          AND document_type = 'signal'
        GROUP BY document_id
    )
    WHERE JSONExtractString(metadata, 'report_id') != ''
      AND timestamp >= now() - INTERVAL 1 MONTH
    ORDER BY distance ASC
    LIMIT {limit}
"""


def _search_candidates(team: Team, embedding: list[float], limit: int = 10) -> list[SignalCandidate]:
    result = execute_hogql_query(
        query_type="SignalsEvalEmbeddingQuery",
        query=CANDIDATE_SEARCH_QUERY,
        team=team,
        placeholders={
            "embedding": ast.Constant(value=embedding),
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "limit": ast.Constant(value=limit),
        },
    )
    candidates = []
    for row in result.results or []:
        document_id, content, report_id, source_product, source_type, distance = row
        candidates.append(
            SignalCandidate(
                signal_id=document_id,
                report_id=report_id,
                content=content,
                source_product=source_product,
                source_type=source_type,
                distance=distance,
            )
        )
    return candidates


class SignalMatchScorer(ScorerWithPartial):
    """Did the pipeline match the signal to the correct report?"""

    def _run_eval_sync(self, output: dict, expected: dict, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        if expected.get("should_be_new"):
            is_new = output.get("is_new", False)
            return Score(
                name=self._name(),
                score=1.0 if is_new else 0.0,
                metadata={
                    "expected": "new_group",
                    "got_new": is_new,
                    "matched_report_id": output.get("matched_report_id"),
                },
            )

        expected_report = expected.get("report_id")
        actual_report = output.get("matched_report_id")
        return Score(
            name=self._name(),
            score=1.0 if expected_report == actual_report else 0.0,
            metadata={
                "expected_report_id": expected_report,
                "actual_report_id": actual_report,
                "is_new": output.get("is_new", False),
            },
        )


class CandidateRetrievalScorer(ScorerWithPartial):
    """Did the retrieval step find at least one candidate from the correct report?

    Helps diagnose whether failures are in retrieval vs. LLM decision-making.
    """

    def _run_eval_sync(self, output: dict, expected: dict, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        if expected.get("should_be_new"):
            return Score(name=self._name(), score=None, metadata={"reason": "Not applicable for new-group cases"})

        expected_report = expected.get("report_id")
        candidate_report_ids: list[str] = output.get("candidate_report_ids", [])
        found = expected_report in candidate_report_ids
        return Score(
            name=self._name(),
            score=1.0 if found else 0.0,
            metadata={
                "expected_report_id": expected_report,
                "candidate_report_ids": list(set(candidate_report_ids)),
                "candidate_count": output.get("candidate_count", 0),
            },
        )


@pytest.mark.django_db
async def eval_signal_matching(pytestconfig, team_with_user, signal_eval_data):
    _, team, _ = team_with_user
    report_id_map = signal_eval_data
    embedding_client = AsyncOpenAI(timeout=60)

    async def task_match_signal(test_case: dict):
        description = test_case["description"]
        source_product = test_case["source_product"]
        source_type = test_case["source_type"]

        # 1. Generate search queries via LLM
        queries = await generate_search_queries(description, source_product, source_type)

        # 2. Embed each search query via OpenAI directly
        query_embeddings: list[list[float]] = []
        for q in queries:
            resp = await embedding_client.embeddings.create(
                model=OPENAI_EMBEDDING_MODEL,
                input=q,
                dimensions=EMBEDDING_DIMENSIONS,
            )
            query_embeddings.append(resp.data[0].embedding)

        # 3. Retrieve candidates from ClickHouse for each query embedding
        candidates_per_query: list[list[SignalCandidate]] = []
        for qe in query_embeddings:
            candidates = await sync_to_async(_search_candidates, thread_sensitive=False)(team, qe)
            candidates_per_query.append(candidates)

        # 4. LLM match decision
        match_result = await match_signal_with_llm(
            description, source_product, source_type, queries, candidates_per_query
        )

        all_candidates = [c for per_query in candidates_per_query for c in per_query]

        if isinstance(match_result, ExistingReportMatch):
            return {
                "is_new": False,
                "matched_report_id": match_result.report_id,
                "candidate_report_ids": [c.report_id for c in all_candidates],
                "candidate_count": len(all_candidates),
            }
        return {
            "is_new": True,
            "new_title": match_result.title,
            "candidate_report_ids": [c.report_id for c in all_candidates],
            "candidate_count": len(all_candidates),
        }

    data = []
    for case in EVAL_CASES:
        expected: dict = {}
        if case.expected_report_key:
            expected["report_id"] = report_id_map[case.expected_report_key]
            expected["should_be_new"] = False
        else:
            expected["should_be_new"] = True

        data.append(
            EvalCase(
                input={
                    "description": case.description,
                    "source_product": case.source_product,
                    "source_type": case.source_type,
                },
                expected=expected,
            )
        )

    openai_client = wrap_openai(
        AsyncOpenAI(timeout=120, api_key=settings.ANTHROPIC_API_KEY, base_url="https://api.anthropic.com/v1/")
    )

    with (
        override_settings(DEBUG=True),
        patch(
            "products.signals.backend.temporal.llm.get_async_llm_client",
            return_value=openai_client,
        ),
    ):
        await MaxPublicEval(
            experiment_name="signal_matching",
            task=task_match_signal,  # type: ignore
            scores=[SignalMatchScorer(), CandidateRetrievalScorer()],
            data=data,
            pytestconfig=pytestconfig,
        )
