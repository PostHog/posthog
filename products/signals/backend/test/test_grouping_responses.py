import json
from collections.abc import Callable

import pytest
from unittest.mock import patch

from pydantic import JsonValue, ValidationError

from products.signals.backend.temporal.grouping import (
    GenerateSearchQueriesInput,
    MatchFound,
    MatchSignalToReportInput,
    NewGroup,
    QueryGenerationResponse,
    SpecificityResult,
    generate_search_queries,
    match_signal_to_report,
    verify_match_specificity,
)
from products.signals.backend.temporal.llm import LLMJsonResponse, LLMResponseValidationError
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeResponse
from products.signals.backend.temporal.safety_filter import SafetyFilterJudgeResponse
from products.signals.backend.temporal.types import (
    ExistingReportMatch,
    MatchResult,
    NewReportMatch,
    ReportContext,
    SignalCandidate,
)

MODULE_PATH = "products.signals.backend.temporal.grouping"


@pytest.mark.parametrize(
    "schema,payload",
    [
        (QueryGenerationResponse, {"queries": [123]}),
        (QueryGenerationResponse, {"queries": []}),
        (QueryGenerationResponse, {"queries": ["query"], "extra": True}),
        (MatchFound, {"reason": "same issue", "match_type": "existing", "signal_id": "signal-1", "query_index": "0"}),
        (MatchFound, {"reason": "same issue", "match_type": "existing", "signal_id": "signal-1", "query_index": True}),
        (NewGroup, {"reason": "new issue", "match_type": "new", "title": "title", "summary": "summary", "extra": True}),
        (SpecificityResult, {"pr_title": "title", "specific_enough": "false", "reason": "reason"}),
        (SpecificityResult, {"pr_title": "title", "specific_enough": True, "reason": "reason", "extra": True}),
        (SafetyFilterJudgeResponse, {"safe": "false"}),
        (SafetyFilterJudgeResponse, {"safe": True, "extra": True}),
        (SafetyFilterJudgeResponse, {"safe": False, "explanation": " "}),
        (SafetyJudgeResponse, {"choice": 1}),
        (SafetyJudgeResponse, {"choice": True, "extra": True}),
        (SafetyJudgeResponse, {"choice": False}),
    ],
)
def test_llm_response_schemas_reject_coercion_extra_fields_and_missing_explanations(
    schema: type[LLMJsonResponse], payload: dict[str, JsonValue]
) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected_error",
    [
        ({"match_type": "existing", "reason": "same issue", "signal_id": "signal-1", "query_index": 0}, None),
        ({"match_type": "new", "reason": "new issue", "title": "title", "summary": "summary"}, None),
        (
            {"match_type": "existing", "reason": "same issue", "signal_id": "signal-1", "query_index": 1},
            "selected query_index",
        ),
        (
            {"match_type": "existing", "reason": "same issue", "signal_id": "missing", "query_index": 0},
            "provided candidates",
        ),
        (
            {"match_type": "existing", "reason": "same issue", "signal_id": "signal-1", "query_index": -1},
            "provided queries",
        ),
        (
            {"match_type": "existing", "reason": "same issue", "signal_id": "signal-1", "query_index": 2},
            "provided queries",
        ),
        ({"match_type": "unknown", "reason": "reason"}, "match_type must be existing or new"),
    ],
)
async def test_matching_validates_selected_query_membership(
    payload: dict[str, JsonValue], expected_error: str | None
) -> None:
    candidates = [
        SignalCandidate(
            signal_id=f"signal-{index}",
            report_id=f"report-{index}",
            content="finding",
            source_product="error_tracking",
            source_type="issue_created",
            distance=0.1,
        )
        for index in (1, 2)
    ]
    input = MatchSignalToReportInput(
        description="a finding",
        source_product="error_tracking",
        source_type="issue_created",
        queries=["query one", "query two"],
        query_results=[[candidates[0]], [candidates[1]]],
        report_contexts={
            candidate.report_id: ReportContext(report_id=candidate.report_id, title="title", signal_count=1)
            for candidate in candidates
        },
    )

    async def fake_call_llm(
        *, validate: Callable[[str], MatchResult], json_response: bool, **_kwargs: object
    ) -> MatchResult:
        assert json_response is True
        return validate(json.dumps(payload))

    with patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm):
        if expected_error:
            with pytest.raises(LLMResponseValidationError, match=expected_error):
                await match_signal_to_report(input)
        else:
            result = await match_signal_to_report(input)
            if payload["match_type"] == "existing":
                assert isinstance(result, ExistingReportMatch)
                assert result.report_id == "report-1"
                assert result.match_metadata.match_query == "query one"
            else:
                assert isinstance(result, NewReportMatch)
                assert result.title == "title"
                assert result.match_metadata.rejected_signal_ids == ["signal-1", "signal-2"]


@pytest.mark.asyncio
async def test_query_generation_preserves_clipping_and_token_truncation() -> None:
    async def fake_call_llm(
        *, validate: Callable[[str], list[str]], json_response: bool, **_kwargs: object
    ) -> list[str]:
        assert json_response is True
        return validate('{"queries": ["one", "two", "three", "four"]}')

    with (
        patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm),
        patch(f"{MODULE_PATH}.truncate_query_to_token_limit", side_effect=lambda query: query[:2]),
    ):
        result = await generate_search_queries(
            GenerateSearchQueriesInput(
                description="a finding",
                source_product="error_tracking",
                source_type="issue_created",
                signal_type_examples=[],
            )
        )
    assert result == ["on", "tw", "th"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        '{"pr_title":"title","specific_enough":true,"reason":"one fix"}',
        '{"pr_title":"title","specific_enough":true,"reason":"one fix","reason":"another fix"}',
    ],
)
async def test_specificity_uses_the_shared_json_parser(text: str) -> None:
    async def fake_call_llm(
        *, validate: Callable[[str], SpecificityResult], json_response: bool, **_kwargs: object
    ) -> SpecificityResult:
        assert json_response is True
        return validate(text)

    with patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm):
        if "another fix" in text:
            with pytest.raises(LLMResponseValidationError, match="Duplicate"):
                await verify_match_specificity(1, "finding", "error_tracking", "issue_created", "title", [])
        else:
            result = await verify_match_specificity(1, "finding", "error_tracking", "issue_created", "title", [])
            assert result.specific_enough is True
            assert result.pr_title == "title"
