import json
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from pydantic import ValidationError

from products.signals.backend.temporal.grouping import _build_matching_prompt, match_and_verify_signal
from products.signals.backend.temporal.types import (
    ExistingReportMatch,
    NewReportMatch,
    ReportContext,
    SignalCandidate,
    SignalData,
)

MODULE_PATH = "products.signals.backend.temporal.grouping"

QUERIES = ["query one", "query two"]
CANDIDATES = [
    [
        SignalCandidate(
            signal_id="sig-1",
            report_id="report-a",
            content="checkout crashes on submit",
            source_product="error_tracking",
            source_type="exception",
            distance=0.1,
        )
    ],
    [
        SignalCandidate(
            signal_id="sig-2",
            report_id="report-b",
            content="checkout conversion dropped",
            source_product="product_analytics",
            source_type="insight_alert",
            distance=0.2,
        )
    ],
]
REPORT_CONTEXTS = {
    "report-a": ReportContext(report_id="report-a", title="Checkout crash", signal_count=3),
    "report-b": ReportContext(report_id="report-b", title="Checkout funnel drop", signal_count=1),
}
REPORT_MEMBERS = {
    "report-a": [
        SignalData(
            signal_id="member-1",
            content="NullPointerException in checkout submit handler",
            source_product="error_tracking",
            source_type="exception",
            source_id="src-1",
            weight=1.0,
            timestamp=datetime(2026, 7, 1, tzinfo=UTC),
        )
    ],
}


def _fake_call_llm(response: dict):
    async def fake(*, team_id, system_prompt, user_prompt, validate, temperature, stage):
        return validate(json.dumps(response))

    return fake


async def _run_match(response: dict):
    with patch(f"{MODULE_PATH}.call_llm", new=_fake_call_llm(response)):
        return await match_and_verify_signal(
            team_id=1,
            description="checkout page throws error",
            source_product="error_tracking",
            source_type="exception",
            queries=QUERIES,
            query_results=CANDIDATES,
            report_contexts=REPORT_CONTEXTS,
            report_members=REPORT_MEMBERS,
        )


@pytest.mark.asyncio
async def test_existing_match_carries_verified_specificity():
    result = await _run_match(
        {
            "reason": "same checkout crash",
            "match_type": "existing",
            "signal_id": "sig-1",
            "query_index": 0,
            "pr_title": "Fix checkout submit crash",
        }
    )

    assert isinstance(result, ExistingReportMatch)
    assert result.report_id == "report-a"
    assert result.match_metadata.match_query == "query one"
    assert result.match_metadata.specificity is not None
    assert result.match_metadata.specificity.pr_title == "Fix checkout submit crash"
    assert result.match_metadata.specificity.specific_enough is True


@pytest.mark.asyncio
async def test_new_group_records_rejected_candidates():
    result = await _run_match(
        {
            "reason": "unrelated to any candidate group",
            "match_type": "new",
            "title": "Login timeout",
            "summary": "Sessions expire during login.",
        }
    )

    assert isinstance(result, NewReportMatch)
    assert result.title == "Login timeout"
    assert result.match_metadata.specificity_rejection is None
    assert sorted(result.match_metadata.rejected_signal_ids) == ["sig-1", "sig-2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {
            "reason": "r",
            "match_type": "existing",
            "signal_id": "hallucinated",
            "query_index": 0,
            "pr_title": "Fix it",
        },
        {"reason": "r", "match_type": "existing", "signal_id": "sig-1", "query_index": 2, "pr_title": "Fix it"},
        {"reason": "r", "match_type": "existing", "signal_id": "sig-1", "query_index": -1, "pr_title": "Fix it"},
        {"reason": "r", "match_type": "existing", "signal_id": "sig-1", "query_index": 0, "pr_title": "   "},
        {"reason": "r", "match_type": "existing", "signal_id": "sig-1", "query_index": 0},
        {"reason": "r", "match_type": "unknown"},
    ],
)
async def test_invalid_responses_fail_validation(response):
    with pytest.raises((ValueError, ValidationError)):
        await _run_match(response)


def test_prompt_includes_member_signals_when_provided():
    prompt = _build_matching_prompt(
        "checkout page throws error",
        "error_tracking",
        "exception",
        QUERIES,
        CANDIDATES,
        REPORT_CONTEXTS,
        report_members=REPORT_MEMBERS,
    )

    assert "CANDIDATE GROUPS" in prompt
    assert "NullPointerException in checkout submit handler" in prompt
    # report-b has no fetched members and must be flagged as such
    assert "(no member signals available)" in prompt


def test_prompt_omits_member_section_without_report_members():
    prompt = _build_matching_prompt(
        "checkout page throws error",
        "error_tracking",
        "exception",
        QUERIES,
        CANDIDATES,
        REPORT_CONTEXTS,
    )

    assert "CANDIDATE GROUPS" not in prompt
