"""Execute a stored verification query and ask TypeSafe Jev whether the fix held."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from django.conf import settings

from pydantic import BaseModel, ConfigDict, Field

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe import typesafe_request

from products.signals.backend.artefact_schemas import VerificationQuery, VerificationQueryResult


class VerificationDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choice: Literal["solved", "not_solved", "insufficient_evidence"]
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float] = Field(default_factory=dict)


class JevVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    answers: dict[str, VerificationDecision]


def execute_verification_query(
    verification: VerificationQuery, *, team: Any, window_start: datetime, window_end: datetime
) -> VerificationQueryResult:
    response = execute_hogql_query(
        query=verification.query,
        team=team,
        placeholders={
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
        },
        workload=Workload.OFFLINE,
    )
    columns = [str(column) for column in (response.columns or [])]
    rows = [list(row) for row in (response.results or [])[:100]]
    return VerificationQueryResult(
        window_start=window_start,
        window_end=window_end,
        columns=columns,
        rows=rows,
    )


def verification_snapshot_matches(verification: VerificationQuery, *, team: Any) -> bool:
    """Re-run the authored baseline so invented or stale rows never become trusted evidence."""

    actual = execute_verification_query(
        verification,
        team=team,
        window_start=verification.snapshot_result.window_start,
        window_end=verification.snapshot_result.window_end,
    )
    return actual.columns == verification.snapshot_result.columns and actual.rows == verification.snapshot_result.rows


def ask_jev_for_verdict(
    verification: VerificationQuery, current_result: VerificationQueryResult
) -> tuple[VerificationDecision, str]:
    api_key = settings.TYPESAFE_API_KEY
    if not api_key:
        raise ValueError("TypeSafe API key is not configured")
    payload: dict[str, Any] = {
        "model": settings.TYPESAFE_DEFAULT_MODEL,
        "state": {
            "check_description": verification.description,
            "query": verification.query,
            "snapshot_result": verification.snapshot_result.model_dump(mode="json"),
            "current_result": current_result.model_dump(mode="json"),
            "success_criteria": verification.success_criteria,
            "inconclusive_conditions": verification.inconclusive_conditions,
        },
        "questions": {
            "issue_status": {
                "type": "choice",
                "instructions": [
                    "Compare snapshot_result with current_result using the supplied query and description.",
                    "Require a meaningful opportunity for the problem to recur.",
                    "Choose insufficient_evidence when the windows are not comparable or opportunity is absent.",
                ],
                "criteria": {
                    "solved": "The current result satisfies the success criteria after meaningful opportunity.",
                    "not_solved": "The current result still demonstrates the reported problem.",
                    "insufficient_evidence": "The evidence cannot support either conclusion.",
                },
            }
        },
    }
    response = typesafe_request(
        "POST",
        f"{settings.TYPESAFE_BASE_URL.rstrip('/')}/v1/systemone",
        api_key=api_key,
        source="signals_verification",
        endpoint="/v1/systemone",
        priority=Priority.BATCH,
        timeout=30,
        json=payload,
    )
    response.raise_for_status()
    parsed = JevVerificationResponse.model_validate(response.json())
    answer = parsed.answers.get("issue_status")
    if answer is None:
        raise ValueError("TypeSafe response did not include issue_status")
    return answer, parsed.model
